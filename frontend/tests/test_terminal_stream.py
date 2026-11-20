"""Exercise the real WebSocket routes, replay flow control and authentication."""
import pytest
from starlette.websockets import WebSocketDisconnect
from frontend.tests.test_action_agents import workspace
from frontend.tests.test_hfl_agent_bridge import bridge, create_action, owner_headers, WORKER


def until(ws, kind):
    for _ in range(20):
        message = ws.receive_json()
        if message['type'] == kind:
            return message
    raise AssertionError('Expected ' + kind)


def setup(workspace):
    api, _, actions, _ = workspace
    session = api.store().start_session(create_action(actions)['id'], {}, 'Stream test')
    return api, api.store().claim_session(session['id'], 'test')


def browser(client, identity):
    return client.websocket_connect('/hfl-corpus/agent-bridge/sessions/' + identity + '/stream', headers={'origin': 'http://testserver'})


def test_stream_roundtrip_and_replay_without_duplicate_input(workspace, authenticated_client):
    api, session = setup(workspace)
    identity = session['id']
    url = '/api/hfl-agent/terminals/' + identity + '/stream'
    with authenticated_client.websocket_connect(url, headers=WORKER) as worker:
        worker.send_json({'token': session['token'], 'after': 0})
        assert until(worker, 'control')['input'] == []
        with browser(authenticated_client, identity) as owner:
            owner.send_json({'csrf': owner_headers()['X-CSRF-Token'], 'after': 0})
            assert until(owner, 'snapshot')['session']['id'] == identity
            for _ in range(2):
                owner.send_json({'type': 'input', 'key': 'same', 'data': 'hello\r'})
                assert until(owner, 'ack')['key'] == 'same'
            control = until(worker, 'control')
            assert control['input'][0]['data'] == 'hello\r'
            assert len(api.store().read_io(identity, 'in')) == 1
            worker.send_json({'type': 'input_ack', 'after': control['input'][0]['seq']})
            worker.send_json({'type': 'output', 'key': 'output1', 'data': 'hello world'})
            assert until(worker, 'ack')['key'] == 'output1'
            snapshot = until(owner, 'snapshot')
            while not snapshot['output']:
                snapshot = until(owner, 'snapshot')
            assert snapshot['output'][0]['data'] == 'hello world'
            cursor = snapshot['output'][-1]['seq']
            owner.send_json({'type': 'output_ack', 'after': cursor})
        # Browser detach must not close the process/session.
        assert api.store().session(identity)['closed'] == 0
        with browser(authenticated_client, identity) as owner:
            owner.send_json({'csrf': owner_headers()['X-CSRF-Token'], 'after': cursor})
            assert until(owner, 'snapshot')['output'] == []


@pytest.mark.parametrize('origin,csrf', [('https://evil.example', 'valid'), ('http://testserver', 'bad')])
def test_browser_stream_rejects_origin_or_csrf(workspace, authenticated_client, origin, csrf):
    _, session = setup(workspace)
    with pytest.raises(WebSocketDisconnect):
        with authenticated_client.websocket_connect('/hfl-corpus/agent-bridge/sessions/' + session['id'] + '/stream', headers={'origin': origin}) as ws:
            ws.send_json({'csrf': owner_headers()['X-CSRF-Token'] if csrf == 'valid' else csrf})
            ws.receive_json()


def test_worker_stream_rejects_wrong_lease(workspace, authenticated_client):
    _, session = setup(workspace)
    with pytest.raises(WebSocketDisconnect):
        with authenticated_client.websocket_connect('/api/hfl-agent/terminals/' + session['id'] + '/stream', headers=WORKER) as ws:
            ws.send_json({'token': 'wrong'})
            ws.receive_json()


def test_runtime_selection_requires_live_host_capability(workspace, authenticated_client):
    api, _, actions, _ = workspace
    item = create_action(actions)
    url = '/hfl-corpus/agent-bridge/actions/' + item['id'] + '/sessions'
    options = {'runtime': 'codex', 'host': 'test'}
    assert authenticated_client.post(url, json=options, headers=owner_headers()).status_code == 409
    api.store().advertise('test', [{'id': 'codex', 'available': True}])
    response = authenticated_client.post(url, json=options, headers=owner_headers())
    assert response.status_code == 200
    assert response.json()['settings']['terminal_runtime'] == 'codex'
    assert response.json()['settings']['agent_host'] == 'test'
