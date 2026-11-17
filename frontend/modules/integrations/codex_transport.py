"""Bounded, read-only JSON-RPC over a local Codex app-server reader.

No shell, authentication changes, task starts, subscriptions, or approval replies.
The executable is host configuration, never a browser-supplied command.
"""
import json
import os
import queue
import subprocess
import threading
import time
from scripts.setup_codex import find_executable

from fastapi import HTTPException

METHODS = {'thread/list', 'thread/turns/list', 'plugin/list'}
MAX_MESSAGE = 8 * 1024 * 1024


def executable():
    try:
        candidate = find_executable()
    except RuntimeError as exc:
        raise HTTPException(503, str(exc)) from None
    if not candidate:
        raise HTTPException(503, 'Codex executable unavailable on the HARQIS host. Ask the administrator to run python scripts/setup_codex.py --install on that host, then sign in locally.')
    return candidate


class CodexRPC:
    def __enter__(self):
        self.messages = queue.Queue(maxsize=128)
        self.sequence = 0
        self.deadline = time.monotonic() + 90
        try:
            self.process = subprocess.Popen([executable(), 'app-server', '--listen', 'stdio://'], stdin=subprocess.PIPE,
                stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0)
        except OSError:
            raise HTTPException(503, 'Codex observation process could not start.') from None
        self.reader = threading.Thread(target=self._read, daemon=True)
        self.reader.start()
        try:
            self._request('initialize', {'clientInfo': {'name': 'harqis_fleet', 'version': '1.0'},
                                        'capabilities': {'experimentalApi': True}})
            self._send({'method': 'initialized'})
        except Exception:
            self.__exit__(None, None, None)
            raise
        return self

    def _read(self):
        try:
            while True:
                line = self.process.stdout.readline(MAX_MESSAGE + 1)
                if not line or len(line) > MAX_MESSAGE:
                    break
                self.messages.put(json.loads(line), timeout=1)
        except (ValueError, OSError, queue.Full):
            pass
        finally:
            try:
                self.messages.put(None, timeout=1)
            except queue.Full:
                pass

    def _send(self, value):
        try:
            self.process.stdin.write((json.dumps(value) + '\n').encode())
            self.process.stdin.flush()
        except (OSError, ValueError):
            raise HTTPException(503, 'Codex daemon disconnected.') from None

    def _request(self, method, params):
        self.sequence += 1
        identity = self.sequence
        self._send({'id': identity, 'method': method, 'params': params})
        deadline = min(self.deadline, time.monotonic() + 20)
        while True:
            try:
                message = self.messages.get(timeout=max(.001, deadline - time.monotonic()))
            except queue.Empty:
                raise HTTPException(504, 'Codex observation timed out; last-known work is retained.') from None
            if not isinstance(message, dict):
                raise HTTPException(503, 'Codex daemon unavailable or response too large.')
            if message.get('id') == identity and 'method' not in message:
                if 'error' in message:
                    code = message['error'].get('code')
                    raise HTTPException(422 if code in {-32601, -32602} else 502,
                                        'Codex observation method unsupported.' if code in {-32601, -32602} else 'Codex observation failed.')
                if not isinstance(message.get('result'), dict):
                    raise HTTPException(502, 'Unsupported Codex response.')
                return message['result']
            if time.monotonic() >= deadline:
                raise HTTPException(504, 'Codex observation timed out.')

    def request(self, method, params):
        if method not in METHODS:
            raise ValueError('Only Codex observation methods are allowed.')
        return self._request(method, params)

    def __exit__(self, *args):
        # Only terminate our reader, never the managed daemon or its tasks.
        self.process.terminate()
        try:
            self.process.wait(timeout=3)
        except subprocess.TimeoutExpired:
            self.process.kill()
            self.process.wait(timeout=3)
        self.reader.join(timeout=2)
        self.process.stdin.close()
        self.process.stdout.close()
