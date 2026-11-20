"""Fleet entry creates no Action; promotion and discard preserve lifecycle boundaries."""
import pytest
import json
from pathlib import Path
from frontend.tests.test_agent_fleet import fleet, post as fleet_post
from frontend.tests.test_hfl_agent_bridge import bridge, owner_headers, WORKER
from frontend.tests.test_action_agents import post
from frontend.tests.test_action_agents import terminal_live_server, browser_auth
from frontend.tests.test_control_focus_browser import browser

ROOT = '/hfl-corpus/agent-bridge'


def opened(fleet, client, runtime='codex'):
    from modules.hfl_corpus.action_agents import store
    from modules.agents.sessions import source
    from modules.integrations import store as connectors
    if runtime in {'codex', 'claude'}:
        connectors.save('frontend-test-user', runtime, {'enabled':True, 'status':'Connected', 'site':'test-installation', 'account_id':'test-installation', 'host':'native-worker'})
    store().advertise('native-worker', [{'id': runtime, 'available': True}])
    agent = fleet_post(client, '/items', {'name': 'Scratch agent', 'runtime': runtime}).json()['item']
    response = fleet_post(client, '/items/' + agent['id'] + '/prepare', {})
    assert response.status_code == 200, response.text
    return agent, store().sessions(source(agent['id'], 'frontend-test-user'))[0]


def test_fleet_promote_once_preserves_live_identity(fleet, bridge, authenticated_client, monkeypatch):
    from modules.hfl_corpus.action_agents import store
    from modules.integrations import service
    agent, session = opened(fleet, authenticated_client)
    assert not session['action_id']
    assert bridge[2].list() == []
    root = ROOT + '/sessions/' + session['id']
    uploaded = authenticated_client.post(root + '/files', files={'files': ('note.txt', b'evidence')}, headers=owner_headers())
    assert uploaded.status_code == 200, uploaded.text
    file_id = uploaded.json()['attachments'][0]['id']
    original = service.canonical
    calls = []
    def uncertain(*args, **kwargs):
        result = original(*args, **kwargs)
        calls.append(result)
        if len(calls) == 1:
            from fastapi import HTTPException
            raise HTTPException(502, 'Response lost')
        return result
    monkeypatch.setattr(service, 'canonical', uncertain)
    payload = {'title': 'Investigate latency', 'expected_outcome': 'Measured result', 'file_ids': [file_id]}
    assert post(authenticated_client, root + '/save-action', payload).status_code == 502
    # An uncertain promotion cannot be discarded; the canonical Action may exist.
    assert post(authenticated_client, root + '/discard', {}).status_code == 409
    saved = post(authenticated_client, root + '/save-action', {**payload, 'title': 'Changed on retry'})
    assert saved.status_code == 200, saved.text
    action_id = saved.json()['action_id']
    assert post(authenticated_client, root + '/save-action', payload).json()['action_id'] == action_id
    assert len(bridge[2].list()) == 1
    action = bridge[2].get(action_id)
    assert action['title'] == payload['title'] and action['status'] == 'open' and not action['agent_enabled']
    assert store().session(session['id'])['settings'] == session['settings']
    assert store().sessions(action_id)[0]['id'] == session['id']
    assert store().configs()['card:' + action_id]['agent_id'] == agent['id']
    from modules.hfl_corpus.agent_bridge import input_manifest
    assert input_manifest('actionable', action_id)['attachments'][0]['name'] == 'note.txt'
    assert post(authenticated_client, root + '/discard', {}).status_code == 409


def test_discard_waits_for_worker_ack_and_keeps_actions_empty(fleet, bridge, authenticated_client):
    from modules.hfl_corpus.action_agents import store
    agent, session = opened(fleet, authenticated_client)
    identity = session['id']
    claimed = post(authenticated_client, '/api/hfl-agent/terminals/' + identity + '/claim', {'host': 'native-worker'}, True)
    assert claimed.status_code == 200, claimed.text
    token = claimed.json()['token']
    poll = {'token': token, 'state': 'idle', 'native_id': 'native-context', 'after': 0}
    response = post(authenticated_client, '/api/hfl-agent/terminals/' + identity + '/poll', poll, True)
    assert response.status_code == 200 and not response.json()['action_closed']
    assert post(authenticated_client, ROOT + '/sessions/' + identity + '/discard', {}).json()['pending']
    assert store().session(identity)['closed']
    assert post(authenticated_client, '/api/hfl-agent/terminals/' + identity + '/poll', {**poll, 'state': 'closed'}, True).status_code == 200
    assert post(authenticated_client, ROOT + '/sessions/' + identity + '/discard', {}).json() == {'pending': False}
    assert authenticated_client.get(ROOT + '/sessions/' + identity).status_code == 404
    assert bridge[2].list() == []


def test_foreign_session_is_inaccessible(fleet, authenticated_client):
    from modules.hfl_corpus.action_agents import store
    _, session = opened(fleet, authenticated_client)
    with store().connect() as db:
        db.execute('UPDATE action_agent_sessions SET owner=? WHERE id=?', ('different-owner', session['id']))
    base = ROOT + '/sessions/' + session['id']
    assert authenticated_client.get(base).status_code == 404
    assert authenticated_client.get(base + '/transcript').status_code == 404
    assert post(authenticated_client, base + '/save-action', {'title': 'Wrong owner'}).status_code == 404
    assert post(authenticated_client, base + '/discard', {}).status_code == 404
    assert post(authenticated_client, base + '/input', {'key': 'x', 'data': 'secret'}).status_code == 404
    from starlette.websockets import WebSocketDisconnect
    with authenticated_client.websocket_connect(base + '/stream', headers={'origin': 'http://testserver'}) as ws:
        ws.send_json({'csrf': owner_headers()['X-CSRF-Token'], 'after': 0})
        with pytest.raises(WebSocketDisconnect):
            ws.receive_json()


def test_partial_file_save_retries_and_action_restore_preserves_inputs(fleet, bridge, authenticated_client, monkeypatch):
    from modules.hfl_corpus import action_agents as api
    agent, session = opened(fleet, authenticated_client)
    root = ROOT + '/sessions/' + session['id']
    uploaded = authenticated_client.post(root + '/files', files={'files': ('input.txt', b'context')}, headers=owner_headers()).json()
    original = api.attach_output
    attempts = []
    async def flaky(*args):
        attempts.append(args[0])
        if len(attempts) == 1:
            from fastapi import HTTPException
            raise HTTPException(502, 'Copy failed')
        return await original(*args)
    monkeypatch.setattr(api, 'attach_output', flaky)
    payload = {'title': 'Track work', 'file_ids': [uploaded['attachments'][0]['id']]}
    assert post(authenticated_client, root + '/save-action', payload).status_code == 502
    assert not api.store().session(session['id'])['action_id']
    action = bridge[2].list()[0]
    bridge[2].update(action['id'], {'version': action['version'], 'title': 'Edited elsewhere'}, actor='owner')
    saved = post(authenticated_client, root + '/save-action', payload)
    assert saved.status_code == 200, saved.text
    assert len(bridge[2].list()) == 1 and attempts == [action['id'], action['id']]
    with api.store().connect() as db:
        db.execute("UPDATE action_agent_sessions SET state='closed',closed=1,native_id='native',worker='native-worker' WHERE id=?", (session['id'],))
    restored = post(authenticated_client, ROOT + '/actions/' + action['id'] + '/sessions', {'restore': session['id']})
    assert restored.status_code == 200, restored.text
    assert restored.json()['native_id'] == 'native' and restored.json()['action_id'] == action['id']
    assert authenticated_client.get(ROOT + '/sessions/' + restored.json()['id'] + '/files').json()['attachments'][0]['name'] == 'input.txt'


def test_fleet_restore_keeps_host_native_context_and_files(fleet, authenticated_client):
    from modules.hfl_corpus.action_agents import store
    agent, session = opened(fleet, authenticated_client)
    root = ROOT + '/sessions/' + session['id']
    authenticated_client.post(root + '/files', files={'files': ('input.txt', b'context')}, headers=owner_headers())
    with store().connect() as db:
        db.execute("UPDATE action_agent_sessions SET state='closed',closed=1,native_id='native',worker='native-worker' WHERE id=?", (session['id'],))
    restored = post(authenticated_client, ROOT + '/fleet/' + agent['id'] + '/sessions', {'restore': session['id']})
    assert restored.status_code == 200, restored.text
    assert restored.json()['native_id'] == 'native'
    assert restored.json()['settings']['agent_host'] == 'native-worker'
    assert authenticated_client.get(ROOT + '/sessions/' + restored.json()['id'] + '/files').json()['attachments'][0]['name'] == 'input.txt'


@pytest.mark.parametrize('width', [390, 1440])
def test_fleet_dialog_save_and_discard(fleet, bridge, authenticated_client, terminal_live_server, browser, width, tmp_path):
    from playwright.sync_api import expect
    from modules.hfl_corpus.action_agents import store
    agent, session = opened(fleet, authenticated_client)
    page = browser.new_page(viewport={'width': width, 'height': 950})
    frontend = Path(__file__).resolve().parents[1]
    errors = []
    page.on('pageerror', lambda error: errors.append(str(error)))
    try:
        terminal_live_server.html = '<html><body><script type="application/json" data-memory-csrf>' + json.dumps(owner_headers()['X-CSRF-Token']) + '</script></body></html>'
        browser_auth(page, authenticated_client, terminal_live_server)
        page.goto(terminal_live_server + '/')
        for name in ('css/hfl-timeline.css', 'vendor/xterm-5.5.0.css'):
            page.add_style_tag(path=str(frontend / 'static' / name))
        for name in ('vendor/xterm-5.5.0.js', 'vendor/xterm-addon-fit-0.10.0.js', 'js/action-agent-workspace.js', 'js/hfl-agent-bridge.js'):
            page.add_script_tag(path=str(frontend / 'static' / name))
        page.evaluate('args=>window.hflAgentBridge.open("fleet",...args)', [agent['id'], agent['name']])
        expect(page.get_by_role('button', name='Save as Action', exact=True)).to_be_enabled()
        assert bridge[2].list() == []
        page.get_by_role('button', name='Close Agent session').click()
        assert not store().session(session['id'])['closed']
        page.evaluate('args=>window.hflAgentBridge.open("fleet",...args)', [agent['id'], agent['name']])
        page.get_by_role('button', name='Save as Action', exact=True).click()
        form = page.get_by_role('dialog').filter(has=page.get_by_role('heading', name='Save session as Action'))
        form.get_by_label('Title', exact=True).fill('Track investigation')
        form.get_by_label('Expected outcome', exact=True).fill('Resolve observed issue')
        page.screenshot(path=str(tmp_path / f'fleet-save-{width}.png'))
        form.get_by_role('button', name='Save as Action', exact=True).click()
        expect(page.get_by_role('button', name='Open Action', exact=True)).to_be_visible()
        assert len(bridge[2].list()) == 1
        assert store().session(session['id'])['action_id']
        # Create a distinct unlinked session after the first terminal ends.
        with store().connect() as db:
            db.execute("UPDATE action_agent_sessions SET state='closed',closed=1 WHERE id=?", (session['id'],))
        page.get_by_role('button', name='New session', exact=True).click()
        expect(page.get_by_role('button', name='Save as Action', exact=True)).to_be_visible()
        page.on('dialog', lambda dialog: dialog.accept())
        page.get_by_label('Actions', exact=True).click()
        page.get_by_role('button', name='Discard session…', exact=True).click()
        expect(page.get_by_role('button', name='Open Action', exact=True)).to_be_visible()
        assert len(store().sessions()) == 1
        assert len(bridge[2].list()) == 1
        assert not errors
    finally:
        page.close()
