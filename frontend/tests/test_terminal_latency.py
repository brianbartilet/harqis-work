"""Repeatable local input-to-PTY-response measurement, without model inference."""
import json
import statistics
import sys
import threading
import time
from types import SimpleNamespace

import httpx
from websockets.sync.client import connect

from frontend.tests.test_action_agents import workspace, terminal_live_server
from frontend.tests.test_hfl_agent_bridge import bridge, create_action, owner_headers, WORKER


def test_terminal_pty_roundtrip_latency(workspace, authenticated_client, terminal_live_server, tmp_path, monkeypatch):
    from scripts.agents.hfl import action_terminal, terminal_runtimes
    from scripts.agents.hfl.agent_bridge_runner import BridgeClient
    api, _, actions, _ = workspace
    from workflows.hfl.action_agent_store import ActionAgentStore
    phases = {'input_store': [], 'output_store': []}
    original_io = ActionAgentStore.io
    def measured_io(self, identity, direction, *args, **kwargs):
        start = time.perf_counter()
        try:
            return original_io(self, identity, direction, *args, **kwargs)
        finally:
            if direction in {'in','out'}:
                phases['input_store' if direction=='in' else 'output_store'].append((time.perf_counter()-start)*1000)
    monkeypatch.setattr(ActionAgentStore, 'io', measured_io)
    script = tmp_path / 'echo.py'
    script.write_text('import sys\nprint("READY",flush=True)\nfor line in sys.stdin:\n print("REPLY:"+line.strip(),flush=True)\n')
    monkeypatch.setattr(terminal_runtimes, 'native_command', lambda *args: ([sys.executable, '-u', str(script)], ''))
    class Workspace:
        def __init__(self, root, *_):
            self.path, self.repo = root, None
        def preserve(self, destination):
            return None
    monkeypatch.setattr(action_terminal, 'Workspace', Workspace)
    db = api.store()
    session = db.start_session(create_action(actions)['id'], {'terminal_runtime': 'codex'}, 'Echo measurement')
    claimed = db.claim_session(session['id'], 'test')
    client = BridgeClient.__new__(BridgeClient)
    client.client = httpx.Client(base_url=terminal_live_server+'/api/hfl-agent/', headers=WORKER)
    runner = SimpleNamespace(REPO_ROOT=tmp_path, spool_root=lambda: tmp_path, redact_credentials=lambda text, env: text)
    worker = action_terminal.TerminalWorker(client, claimed, runner)
    failures = []
    def run():
        try:
            worker.run()
        except Exception as error:
            failures.append(error)
        finally:
            if worker.transport:
                worker.transport.close()
    thread = threading.Thread(target=run, daemon=True)
    thread.start()
    samples = []
    try:
        with connect(terminal_live_server.replace('http:', 'ws:')+'/hfl-corpus/agent-bridge/sessions/'+session['id']+'/stream',
                     origin=terminal_live_server, additional_headers={'Cookie':'session='+authenticated_client.cookies.get('session')}, proxy=None) as ws:
            ws.send(json.dumps({'csrf': owner_headers()['X-CSRF-Token'], 'after': 0}))
            def output_until(marker):
                output = ''
                deadline = time.monotonic()+20
                while marker not in output:
                    assert time.monotonic()<deadline, 'No PTY response within 20 seconds.'
                    message = json.loads(ws.recv(timeout=15))
                    if message.get('output'):
                        output += ''.join(chunk['data'] for chunk in message['output'])
                        ws.send(json.dumps({'type':'output_ack', 'after':message['output'][-1]['seq']}))
            output_until('READY')
            for index in range(12):
                # Includes settled/idle workers, not just a continuously busy stream.
                time.sleep(.1 if index % 3 else .4)
                start = time.perf_counter()
                ws.send(json.dumps({'type':'input', 'key':str(index), 'data':f'ping-{index}\r'}))
                output_until(f'REPLY:ping-{index}')
                samples.append((time.perf_counter()-start)*1000)
    finally:
        db.edit_session(session['id'], closed=True)
        thread.join(timeout=15)
        client.client.close()
    assert not thread.is_alive()
    assert not failures
    assert len(samples) == 12
    report = {'median_ms':round(statistics.median(samples),1), 'p95_ms':round(sorted(samples)[-1],1), 'samples_ms':[round(value,1) for value in samples]}
    print('TERMINAL_LATENCY '+json.dumps(report))
    print('TERMINAL_STORAGE '+json.dumps({key:round(statistics.median(values),1) for key,values in phases.items()}))
