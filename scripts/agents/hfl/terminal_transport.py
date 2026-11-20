"""Persistent worker stream with keyed output retries and pushed input."""
import json
import queue
import threading
import time
import uuid

from websockets.sync.client import connect


class TerminalTransport:
    def __init__(self, worker):
        self.worker = worker
        self.ws = None
        self.pending = {}
        self.guard = threading.Lock()
        self.control = {'input': [], 'cols': worker.session['cols'], 'rows': worker.session['rows'], 'close': False}
        self.after = worker.after

    def open(self):
        base = str(self.worker.client.client.base_url)
        url = base.replace('https://', 'wss://', 1).replace('http://', 'ws://', 1)
        ws = connect(url + self.worker.prefix + '/stream',
                     additional_headers={'Authorization': self.worker.client.client.headers['Authorization']},
                     open_timeout=5, close_timeout=1, max_size=8 * 1024 * 1024, max_queue=8, proxy=None)
        ws.send(json.dumps({'token': self.worker.token, 'after': self.after}))
        self.ws = ws
        threading.Thread(target=self.read, args=(ws,), daemon=True).start()

    def read(self, ws):
        try:
            for raw in ws:
                message = json.loads(raw)
                with self.guard:
                    if self.ws is not ws:
                        return
                    if message['type'] == 'control':
                        self.control = message
                    else:
                        target = self.pending.get(message.get('key'))
                        if target:
                            target.put_nowait(message)
        except Exception:
            pass
        finally:
            with self.guard:
                if self.ws is not ws:
                    return
                for target in self.pending.values():
                    try:
                        target.put_nowait({'type': 'disconnected'})
                    except queue.Full:
                        pass

    def call(self, suffix, **payload):
        key = payload.get('key') or uuid.uuid4().hex
        message = {**payload, 'key': key, 'type': 'output' if suffix == '/output' else 'heartbeat'}
        deadline = time.monotonic() + 60
        while True:
            reply = queue.Queue(maxsize=1)
            try:
                if self.ws is None:
                    self.open()
                with self.guard:
                    self.pending[key] = reply
                self.ws.send(json.dumps(message))
                result = reply.get(timeout=5)
                if result['type'] == 'error':
                    raise ValueError(result['message'])
                if result['type'] != 'ack':
                    raise ConnectionError('Terminal stream disconnected.')
                return result['result']
            except ValueError:
                raise
            except Exception:
                self.close()
                if time.monotonic() >= deadline:
                    raise ConnectionError('Terminal stream unavailable for 60 seconds.')
                time.sleep(.5)
            finally:
                with self.guard:
                    self.pending.pop(key, None)

    def snapshot(self):
        with self.guard:
            return dict(self.control)

    def acknowledge(self, after):
        self.after = after
        try:
            if self.ws:
                self.ws.send(json.dumps({'type': 'input_ack', 'after': after}))
        except Exception:
            # Same worker retains its cursor. Reconnect hello reconciles it.
            pass

    def close(self):
        ws, self.ws = self.ws, None
        if ws:
            ws.close()
