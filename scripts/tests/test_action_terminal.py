import subprocess
import sys
import time
import zipfile

import pytest

from scripts.agents.hfl.action_terminal import Workspace, Pty, git


def test_idle_collection_retries_failed_upload_and_discovers_later_files(tmp_path):
    from scripts.agents.hfl.action_terminal import TerminalWorker
    from types import SimpleNamespace
    attempts = []
    def send(url, **kwargs):
        attempts.append(kwargs['content'])
        if len(attempts) == 1:
            raise ConnectionError('Temporary outage')
        return SimpleNamespace(raise_for_status=lambda: None)
    worker = TerminalWorker(SimpleNamespace(client=SimpleNamespace(post=send)),
        {'id':'test','token':'test','native_id':''}, None)
    (tmp_path/'first.txt').write_text('first')
    worker.collect_outputs(tmp_path)
    assert worker.sent == {}
    worker.collect_outputs(tmp_path)
    (tmp_path/'later.txt').write_text('later')
    worker.collect_outputs(tmp_path)
    worker.collect_outputs(tmp_path)
    assert attempts == [b'first', b'first', b'later']


def test_worktree_preserves_committed_uncommitted_and_untracked_changes(tmp_path):
    repo = tmp_path / 'repo'
    repo.mkdir()
    git(repo, 'init')
    git(repo, 'config','user.name','Test')
    git(repo, 'config','user.email','test@example.test')
    (repo/'tracked.txt').write_text('original')
    git(repo,'add','tracked.txt');git(repo,'commit','-m','Initial')
    workspace = Workspace(tmp_path/'session','test-session',{'agent_repository':str(repo)})
    assert git(workspace.path,'branch','--show-current').strip() == 'actions-agent/test-session'
    (workspace.path/'tracked.txt').write_text('committed change')
    git(workspace.path,'commit','-am','Agent change')
    (workspace.path/'tracked.txt').write_text('uncommitted change')
    (workspace.path/'new.txt').write_text('untracked content')
    outputs=tmp_path/'outputs';outputs.mkdir()
    archive=workspace.preserve(outputs)
    with zipfile.ZipFile(archive) as z:
        assert b'committed change' in z.read('commits.patch')
        assert b'uncommitted change' in z.read('working-tree.patch')
        assert z.read('untracked/new.txt')==b'untracked content'
    workspace.cleanup()
    assert not workspace.path.exists()
    assert (repo/'tracked.txt').read_text()=='original'
    assert git(repo,'rev-parse','--verify',workspace.branch).strip()


def test_native_pty_roundtrip_and_resize(tmp_path):
    import os
    if os.name=='nt':
        pytest.importorskip('winpty')
    script=tmp_path/'terminal.py'
    script.write_text('print("READY", flush=True)\nvalue=input()\nprint("RECEIVED:"+value, flush=True)\ninput()\n')
    terminal=Pty([sys.executable,str(script)],tmp_path,dict(os.environ),80,24)
    output=''
    try:
        deadline=time.monotonic()+10
        while 'READY' not in output and time.monotonic()<deadline:
            output+=terminal.read()
        assert 'READY' in output
        terminal.resize(30,100)
        terminal.write('/help\r' if os.name=='nt' else '/help\n')
        while 'RECEIVED:/help' not in output and time.monotonic()<deadline:
            output+=terminal.read()
        assert 'RECEIVED:/help' in output
    finally:
        terminal.close()


@pytest.mark.parametrize('native_state,expected', [('idle','expired'), ('running','closed')])
def test_idle_expiry_archives_but_does_not_expire_active_turn(tmp_path, monkeypatch, native_state, expected):
    import json
    from types import SimpleNamespace
    from scripts.agents.hfl import action_terminal as module
    ticks = [0.0]
    def clock():
        ticks[0] += .4
        return ticks[0]
    monkeypatch.setattr(module.time, 'monotonic', clock)
    class FakeWorkspace:
        def __init__(self, root, identity, settings):
            self.path=root; self.repo=None
        def preserve(self, root):
            return None
    class FakePty:
        def __init__(self, command, cwd, env, cols, rows):
            from pathlib import Path
            Path(env['HFL_TERMINAL_CONTROL']).write_text(json.dumps({'state':native_state,'native_id':'native'}))
        def alive(self): return True
        def read(self): return 'Visible output\r\n'
        def close(self): pass
        def resize(self,*args): pass
    monkeypatch.setattr(module,'Workspace',FakeWorkspace)
    monkeypatch.setattr(module,'Pty',FakePty)
    runner=SimpleNamespace(REPO_ROOT=tmp_path,spool_root=lambda:tmp_path,
                           hermes_command=lambda:([sys.executable,'-c',''],tmp_path),
                           HERMES_PROGRAM='',redact_credentials=lambda text,env:text)
    class Worker(module.TerminalWorker):
        def call(self,suffix,**payload):
            if suffix=='/output': return {}
            self.states.append(payload['state'])
            return {'granted':True,'close':len(self.states)>6,'input':[],
                    'cols':80,'rows':24,'expiry_minutes':.01,'action_closed':False}
        def upload(self,path): self.files.append(path.name)
    worker=Worker(None,{'id':'test','token':'test','native_id':'','rows':24,'cols':80,'settings':{}},runner)
    worker.states=[];worker.files=[]
    worker.run()
    assert worker.states[-1]==expected
    assert 'session-transcript.txt' in worker.files

@pytest.mark.parametrize('failure', ['connect', 'gateway', 'empty'])
def test_terminal_transport_retries_same_key(monkeypatch, failure):
    import httpx
    from scripts.agents.hfl.agent_bridge_runner import BridgeClient
    from scripts.agents.hfl import agent_bridge_runner
    calls = []
    def handle(request):
        calls.append(request.content)
        if len(calls) == 1:
            if failure == 'connect':
                raise httpx.ConnectError('offline', request=request)
            return httpx.Response(503 if failure == 'gateway' else 200)
        return httpx.Response(200, json={'ok': True})
    monkeypatch.setattr(agent_bridge_runner.time, 'sleep', lambda _: None)
    bridge = BridgeClient.__new__(BridgeClient)
    with httpx.Client(base_url='http://test/', transport=httpx.MockTransport(handle)) as client:
        bridge.client = client
        assert bridge.call('terminals/test/output', {'key': 'same-key', 'data': 'hello'}) == {'ok': True}
    assert len(calls) == 2 and calls[0] == calls[1]


@pytest.mark.parametrize('path,status,expected', [('terminals/test/poll', 503, 4), ('terminals/test/poll', 409, 1), ('terminals/test/claim', 503, 1)])
def test_terminal_transport_retries_bounded_and_respects_lease(monkeypatch, path, status, expected):
    import httpx
    from scripts.agents.hfl.agent_bridge_runner import BridgeClient
    from scripts.agents.hfl import agent_bridge_runner
    calls = []
    def handle(request):
        calls.append(request)
        return httpx.Response(status)
    monkeypatch.setattr(agent_bridge_runner.time, 'sleep', lambda _: None)
    bridge = BridgeClient.__new__(BridgeClient)
    with httpx.Client(base_url='http://test/', transport=httpx.MockTransport(handle)) as client:
        bridge.client = client
        with pytest.raises(httpx.HTTPStatusError):
            bridge.call(path, {'token': 'lease'})
    assert len(calls) == expected


def test_pasted_image_download_and_prompt_reference(tmp_path):
    import hashlib
    import json
    import httpx
    from types import SimpleNamespace
    from scripts.agents.hfl.action_terminal import TerminalWorker
    content = b'clipboard image'
    calls = []
    def request(req):
        assert req.headers['X-Terminal-Lease'] == 'lease'
        assert req.url.path == '/terminals/session/inputs/image'
        return httpx.Response(200, content=content)
    client = httpx.Client(base_url='https://worker.test/', transport=httpx.MockTransport(request))
    worker = TerminalWorker(SimpleNamespace(client=client), {'id':'session','token':'lease','native_id':''}, None)
    worker.call = lambda *args, **kwargs: calls.append((args, kwargs))
    writes = []
    terminal = SimpleNamespace(write=writes.append)
    image = {'id':'image','filename':'a'*32+'.png','size':len(content),'digest':hashlib.sha256(content).hexdigest()}
    worker.deliver_input({'seq':1,'type':'image','data':json.dumps(image)}, terminal, tmp_path)
    assert (tmp_path/image['filename']).read_bytes() == content
    assert writes == [' ' + json.dumps((tmp_path/image['filename']).resolve().as_posix()) + ' ']
    assert '\r' not in writes[0] and '\n' not in writes[0]
    worker.deliver_input({'seq':2,'data':'review it'}, terminal, tmp_path)
    assert writes[-1] == 'review it'
    image['digest'] = 'wrong'
    worker.deliver_input({'seq':3,'type':'image','data':json.dumps(image)}, terminal, tmp_path)
    assert len(writes) == 2
    assert calls[-1][0] == ('/output',)
    assert 'could not be loaded' in calls[-1][1]['data']
    client.close()
