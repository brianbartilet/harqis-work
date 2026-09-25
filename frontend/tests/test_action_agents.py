"""Action workspace lifecycle, shared worker capacity, and native UI regression."""
import json
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from uuid import uuid4

import pytest

from frontend.tests.test_hfl_agent_bridge import bridge, create_action, owner_headers, WORKER


@pytest.fixture
def workspace(bridge, monkeypatch):
    from modules.hfl_corpus import action_agents as api
    from modules.app_settings.store import DEFAULTS
    module, store, actions = bridge
    settings = dict(DEFAULTS)
    monkeypatch.setattr(api, 'read_settings', lambda: dict(settings))
    monkeypatch.setattr(module, 'read_settings', lambda: dict(settings))
    return api, module, actions, settings


def post(client, path, data, worker=False):
    return client.post(path, json=data, headers=WORKER if worker else owner_headers())


def test_configuration_inherits_live_defaults_and_preserves_overrides(workspace, authenticated_client):
    api, module, actions, settings = workspace
    item = create_action(actions)
    root = '/hfl-corpus/agent-bridge'
    assert post(authenticated_client, root+'/presets', {'name':'Coding','overrides':{'agent_max_turns':45}}).status_code == 200
    assert post(authenticated_client, root+'/actions/'+item['id']+'/configuration', {'preset':'Coding','overrides':{'agent_model':'fixed'}}).status_code == 200
    settings['agent_provider'] = 'new-provider'
    settings['agent_model'] = 'changed-default'
    resolved = module.source_snapshot('actionable', item['id'])['execution_settings']
    assert resolved['agent_provider'] == 'new-provider'
    assert resolved['agent_model'] == 'fixed'
    assert resolved['agent_max_turns'] == 45
    assert post(authenticated_client, root+'/presets', {'name':'Coding','overrides':{'agent_max_turns':50}}).status_code == 200
    assert api.effective(item['id'])['agent_max_turns'] == 50
    assert post(authenticated_client, root+'/presets', {'name':'Bad','overrides':{'agent_concurrency':20}}).status_code == 400


def test_terminal_io_restore_and_download_on_completed_card(workspace, authenticated_client):
    api, _, actions, _ = workspace
    item = create_action(actions)
    actions.update(item['id'], {'status':'done','version':item['version']}, actor='owner')
    root = '/hfl-corpus/agent-bridge'
    response = post(authenticated_client, root+'/actions/'+item['id']+'/sessions', {})
    assert response.status_code == 200, response.text
    session = response.json()
    same = post(authenticated_client, root+'/actions/'+item['id']+'/sessions', {}).json()
    assert same['id'] == session['id']
    identity = session['id']
    assert post(authenticated_client, root+'/sessions/'+identity+'/input', {'key':'1','data':'/help\r'}).status_code == 409
    claimed = post(authenticated_client, '/api/hfl-agent/terminals/'+identity+'/claim', {'host':'test'}, True).json()
    assert 'token' in claimed
    assert 'token' not in authenticated_client.get(root+'/sessions/'+identity).json()['session']
    base = {'token':claimed['token'],'state':'idle','native_id':'native-session','after':0}
    assert post(authenticated_client, '/api/hfl-agent/terminals/'+identity+'/poll', base, True).status_code == 200
    for _ in range(2):
        assert post(authenticated_client, root+'/sessions/'+identity+'/input', {'key':'same','data':'/help\r'}).status_code == 200
    assert len(api.store().read_io(identity,'in')) == 1
    output = {'token':claimed['token'],'key':'chunk','data':'\x1b[32mhello\x1b[0m'}
    assert post(authenticated_client, '/api/hfl-agent/terminals/'+identity+'/output', output, True).status_code == 200
    assert authenticated_client.get(root+'/sessions/'+identity+'/transcript').text == 'hello'
    assert post(authenticated_client, root+'/sessions/'+identity, {'saved':True}).status_code == 200
    assert post(authenticated_client, '/api/hfl-agent/terminals/'+identity+'/poll', {**base,'state':'expired'}, True).status_code == 200
    restored = post(authenticated_client, root+'/actions/'+item['id']+'/sessions', {'restore':identity}).json()
    assert restored['native_id'] == 'native-session'
    assert restored['id'] != identity


def test_capacity_is_atomic_across_terminal_claims(workspace):
    api, _, actions, _ = workspace
    db = api.store()
    sessions = [db.start_session(create_action(actions)['id'], {}, 'test') for _ in range(6)]
    claimed = [db.claim_session(s['id'],'test') for s in sessions]
    with ThreadPoolExecutor(max_workers=6) as pool:
        answers = list(pool.map(lambda s: db.heartbeat_session(s['id'],s['token'],'waiting','native',2), claimed))
    assert sum(answer['granted'] for answer in answers) == 2
    with db.connect() as connection:
        assert db.busy_count(connection) == 2
    running = next(s for s in db.sessions() if s['state']=='running')
    original = next(s for s in claimed if s['id']==running['id'])
    db.heartbeat_session(original['id'],original['token'],'idle','native',2)
    with db.connect() as connection:
        assert db.busy_count(connection) == 1


def test_automatic_and_interactive_share_limit(workspace):
    api, module, actions, _ = workspace
    one, two = create_action(actions), create_action(actions)
    automatic = module.enqueue('actionable',one['id'],str(uuid4()),'owner')
    db = api.store()
    db.claim(automatic['id'],'hermes',concurrency=1)
    session = db.start_session(two['id'],{},'test')
    claimed = db.claim_session(session['id'],'test')
    assert not db.heartbeat_session(session['id'],claimed['token'],'waiting','native',1)['granted']
    assert db.heartbeat_session(session['id'],claimed['token'],'waiting','native',2)['granted']
    third = module.enqueue('actionable', create_action(actions)['id'],str(uuid4()),'owner')
    from workflows.hfl.agent_bridge_store import BridgeConflict
    with pytest.raises(BridgeConflict, match='capacity'):
        db.claim(third['id'],'hermes',concurrency=2)


def test_generated_files_versioned_and_survive_session_removal(workspace, authenticated_client):
    api, _, actions, _ = workspace
    item = create_action(actions)
    db = api.store()
    s = db.start_session(item['id'],{},'test')
    claimed = db.claim_session(s['id'],'test')
    url = '/api/hfl-agent/terminals/'+s['id']+'/files/result.txt'
    headers = {**WORKER, 'X-Terminal-Lease':claimed['token']}
    for data in (b'one',b'one',b'two'):
        response = authenticated_client.post(url,content=data,headers=headers)
        assert response.status_code == 200, response.text
    from modules.hfl_corpus.attachments import source_store
    attachments, source = source_store('actionable',item['id'])
    assert len(attachments.list(source)) == 2
    db.heartbeat_session(s['id'],claimed['token'],'closed','native',1)
    db.forget(s['id'])
    assert len(attachments.list(source)) == 2


def test_transport_requires_owner_csrf_and_worker_lease(workspace, authenticated_client):
    api, _, actions, _ = workspace
    item = create_action(actions)
    s = api.store().start_session(item['id'],{},'test')
    api.store().claim_session(s['id'],'test')
    assert authenticated_client.post('/hfl-corpus/agent-bridge/sessions/'+s['id'],json={'closed':True}).status_code == 403
    assert post(authenticated_client, '/api/hfl-agent/terminals/'+s['id']+'/poll', {'token':'bad','state':'idle'}, True).status_code == 409


def test_stale_worker_releases_capacity(workspace):
    api, _, actions, _ = workspace
    db = api.store()
    s = db.start_session(create_action(actions)['id'],{},'test')
    c = db.claim_session(s['id'],'test')
    db.heartbeat_session(s['id'],c['token'],'waiting','native',1)
    with db.connect() as connection:
        connection.execute("UPDATE action_agent_sessions SET heartbeat='2000-01-01' WHERE id=?", (s['id'],))
    db.expire_sessions()
    assert db.session(s['id'])['state']=='failed'
    assert db.heartbeat_session(s['id'],c['token'],'running','native',1)['close']


def test_fast_terminal_poll_preserves_lease_cursor_and_close(workspace, authenticated_client, monkeypatch):
    api, module, actions, _ = workspace
    db = api.store()
    s = db.start_session(create_action(actions)['id'], {}, 'test')
    claimed = db.claim_session(s['id'], 'test')
    db.io(s['id'], 'in', 'one', 'hello')
    def unexpected(*args, **kwargs):
        raise AssertionError('Fast input delivery must not query the action service')
    monkeypatch.setattr(module, 'action_call', unexpected)
    path = '/api/hfl-agent/terminals/'+s['id']+'/poll'
    payload = {'token':claimed['token'], 'io_only':True, 'after':0}
    reply = post(authenticated_client, path, payload, True).json()
    assert [event['data'] for event in reply['input']] == ['hello']
    assert not reply['close']
    assert 'granted' not in reply
    payload['after'] = reply['input'][-1]['seq']
    assert post(authenticated_client, path, payload, True).json()['input'] == []
    assert post(authenticated_client, path, {**payload, 'token':'bad'}, True).status_code == 409
    db.edit_session(s['id'], closed=True)
    assert post(authenticated_client, path, payload, True).json()['close']


def test_expiry_settings_validation():
    from modules.app_settings.store import validate_settings
    assert validate_settings({})['agent_session_expiry_minutes'] == 60
    assert validate_settings({'agent_session_expiry_minutes':15})['agent_session_expiry_minutes'] == 15
    for invalid in (0, -1, True, '1.5', 10081):
        with pytest.raises((ValueError,TypeError)):
            validate_settings({'agent_session_expiry_minutes':invalid})


def test_native_workspace_browser(workspace, authenticated_client, tmp_path):
    from urllib.parse import urlparse
    playwright = pytest.importorskip('playwright.sync_api')
    api, _, actions, _ = workspace
    item = create_action(actions)
    actions.update(item['id'], {'version':item['version'], 'notes':'**Review checklist**\n\n'+'\n'.join('- Check item '+str(i) for i in range(20))}, actor='owner')
    frontend = Path(__file__).resolve().parents[1]
    with playwright.sync_playwright() as p:
        browser = p.chromium.launch(channel='chrome',headless=True)
        page = browser.new_page(viewport={'width':1440,'height':1000})
        errors=[]
        input_requests=[]
        page.on('pageerror',lambda e:errors.append(str(e)))
        def route(r):
            parsed=urlparse(r.request.url)
            if parsed.path.endswith('/input'):
                input_requests.append(json.loads(r.request.post_data)['data'])
            if parsed.path=='/':
                r.fulfill(content_type='text/html',body='<html><body style="background:#080f1e;color:white;font-family:Arial,sans-serif"><script type="application/json" data-memory-csrf>'+json.dumps(owner_headers()['X-CSRF-Token'])+'</script></body></html>')
            else:
                response=authenticated_client.request(r.request.method,parsed.path+('?' + parsed.query if parsed.query else ''),content=r.request.post_data,headers={k:v for k,v in r.request.headers.items() if k.lower() in {'content-type','x-csrf-token'}})
                r.fulfill(status=response.status_code,content_type=response.headers.get('content-type','application/json'),body=response.content)
        page.route('https://workspace.test/**',route)
        page.goto('https://workspace.test/')
        for name in ('css/hfl-timeline.css','vendor/xterm-5.5.0.css'):
            page.add_style_tag(path=str(frontend/'static'/name))
        for name in ('vendor/xterm-5.5.0.js','vendor/xterm-addon-fit-0.10.0.js','js/hfl-input-attachments.js','js/action-agent-workspace.js','js/hfl-agent-bridge.js'):
            page.add_script_tag(path=str(frontend/'static'/name))
        page.evaluate('(item)=>window.hflAgentBridge.open("actionable",item.id,item.title)',item)
        page.get_by_role('heading',name='Ready to work on this action?').wait_for()
        playwright.expect(page.locator('.agent-header-status')).to_have_text('No session · Start to begin')
        page.get_by_label('Actions agent help',exact=True).click()
        playwright.expect(page.locator('.agent-header-help-body')).to_contain_text('click inside the terminal to type')
        page.get_by_label('Actions agent help',exact=True).click()
        playwright.expect(page.get_by_role('button',name='Start session',exact=True)).to_be_visible()
        page.screenshot(path=str(tmp_path/'actions-agent-empty.png'))
        sidebar = page.get_by_role('complementary', name='Action information and controls')
        page.get_by_role('heading',name='Agent actions session',exact=True).wait_for()
        playwright.expect(sidebar.locator('.markdown-body strong')).to_have_text('Review checklist')
        assert sidebar.locator('.markdown-body li').count() == 20
        assert sidebar.locator('.agent-action-summary').inner_text().find(item['prompt']) >= 0
        assert sidebar.locator('.agent-results-task input, .agent-results-task textarea').count() == 0
        assert not page.locator('.agent-details').evaluate('(e)=>e.open')
        page.get_by_text('Agent details',exact=True).click()
        page.get_by_role('button',name='Configure agent',exact=True).click()
        page.get_by_role('heading',name='Configure action agent').wait_for()
        page.get_by_role('button',name='Close',exact=True).click()
        page.get_by_role('button',name='Start session',exact=True).click()
        playwright.expect(page.locator('.agent-session-empty')).not_to_be_visible()
        page.get_by_text('Waiting for a worker to connect…').wait_for()
        session = api.store().sessions(item['id'])[0]
        claimed = api.store().claim_session(session['id'], 'test')
        response = authenticated_client.post('/api/hfl-agent/terminals/'+session['id']+'/files/lorem-ipsum.txt',
            content=b'Generated text', headers={**WORKER, 'X-Terminal-Lease':claimed['token']})
        assert response.status_code == 200
        page.get_by_role('button', name='Refresh', exact=True).click()
        link = page.get_by_role('link', name='Download '+response.json()['name'], exact=True)
        link.wait_for()
        assert authenticated_client.get(urlparse(link.get_attribute('href')).path).content == b'Generated text'
        assert page.get_by_text('No results yet', exact=True).count() == 0
        toolbar=page.get_by_role('region',name='Session controls')
        assert toolbar.get_by_role('combobox', name='Agent session').count() == 1
        assert toolbar.get_by_role('combobox',name='Agent session').bounding_box()['width'] <= 220
        playwright.expect(toolbar.get_by_role('button',name='New session',exact=True)).to_be_visible()
        assert sidebar.locator('.agent-details').get_by_role('link',name='Agent default settings').get_attribute('target') == '_blank'
        assert sidebar.locator('.agent-results-footer').count() == 0
        playwright.expect(sidebar.get_by_role('heading',name='Attachments · 1')).to_be_visible()
        row=sidebar.locator('.agent-output-file')
        assert row.evaluate('(e)=>getComputedStyle(e).display') == 'grid'
        view_box=row.get_by_role('button').bounding_box()
        download_box=row.get_by_role('link').bounding_box()
        assert 0 <= download_box['x']-view_box['x']-view_box['width'] < 8
        page.get_by_role('button',name='View '+response.json()['name'],exact=True).click()
        playwright.expect(page.locator('.agent-input-preview pre')).to_have_text('Generated text')
        page.locator('.agent-input-preview').get_by_role('button',name='Close',exact=True).click()
        terminal = page.get_by_label('Native Hermes terminal')
        before = terminal.bounding_box()
        assert .24 < sidebar.bounding_box()['width']/page.locator('.action-agent-dialog').bounding_box()['width'] < .30
        assert page.locator('.action-agent-dialog').bounding_box()['width'] < 1440*.90
        sidebar.evaluate('(el)=>{el.scrollTop=el.scrollHeight;}')
        assert sidebar.evaluate('(el)=>el.scrollTop') > 0
        assert terminal.bounding_box() == before
        assert page.locator('.action-agent-dialog').evaluate('(el)=>el.scrollHeight<=el.clientHeight+1')
        page.get_by_text('Starting Hermes…', exact=True).wait_for()
        page.locator('.xterm-helper-textarea').focus()
        typed = 'typing should preserve every character in order'
        page.keyboard.type(typed)
        import time
        deadline = time.monotonic()+5
        while ''.join(input_requests) != typed and time.monotonic()<deadline:
            page.wait_for_timeout(50)
        assert ''.join(input_requests) == typed
        assert len(input_requests) < len(typed)
        api.store().heartbeat_session(session['id'],claimed['token'],'failed','restorable-native',2)
        notice=page.get_by_role('region',name='Session connection')
        playwright.expect(notice).to_contain_text('This transcript is read-only.')
        playwright.expect(page.locator('.agent-header-status')).to_have_text('Disconnected · Restore session')
        page.get_by_role('button',name='Restore session',exact=True).click()
        playwright.expect(notice).not_to_be_visible()
        restored=api.store().sessions(item['id'])[0]
        assert restored['id'] != session['id']
        assert restored['native_id'] == 'restorable-native'
        sidebar.evaluate('(el)=>{el.scrollTop=0;}')
        page.screenshot(path=str(tmp_path/'actions-agent-desktop.png'))
        page.set_viewport_size({'width':390,'height':844})
        playwright.expect(sidebar).not_to_be_visible()
        assert terminal.bounding_box()['width'] > 300
        page.get_by_role('button', name='Action details', exact=True).click()
        playwright.expect(sidebar).to_be_visible()
        page.get_by_role('button', name='Action details', exact=True).click()
        playwright.expect(sidebar).not_to_be_visible()
        page.screenshot(path=str(tmp_path/'actions-agent-mobile.png'))
        assert not errors
        browser.close()
