"""Fleet persistence, snapshots, capability boundaries and owner UI."""
import io
import json
from uuid import uuid4
from pathlib import Path
from urllib.parse import urlparse

import pytest
from PIL import Image
from frontend.tests.test_hfl_agent_bridge import bridge, create_action, owner_headers


def post(client, path, data):
    return client.post('/agents/api' + path, json=data, headers=owner_headers())


@pytest.fixture
def fleet(bridge, monkeypatch, tmp_path):
    from modules.agents import service
    monkeypatch.setenv('HARQIS_CONNECTORS_DB', str(tmp_path / 'connectors.sqlite3'))
    monkeypatch.delenv('HARQIS_HERMES_URL', raising=False)
    monkeypatch.delenv('HARQIS_HERMES_API_KEY', raising=False)
    return service


def test_seed_is_idempotent_and_migrates_presets(fleet):
    from modules.hfl_corpus.action_agents import store
    store().configure('preset:Research', {'overrides': {'agent_model': 'test-model'}})
    one = fleet.initialize().list()
    two = fleet.initialize().list()
    assert one == two
    assert {a['name'] for a in one} == {'Default agent', 'HARQIS Butler', 'Research'}
    assert next(a for a in one if a['name'] == 'Research')['overrides']['agent_model'] == 'test-model'


def test_version_deactivation_and_frozen_session(fleet, bridge, authenticated_client):
    from modules.hfl_corpus import action_agents
    client = authenticated_client
    item = post(client, '/items', {'name':'Research', 'instructions':'Read all evidence', 'overrides':{'agent_model':'first'}}).json()['item']
    action = create_action(bridge[2])
    path = '/hfl-corpus/agent-bridge/actions/' + action['id']
    result = client.post(path + '/configuration', json={'agent_id':item['id'], 'overrides':{'agent_model':'action-model'}}, headers=owner_headers())
    assert result.status_code == 200, result.text
    session = client.post(path+'/sessions', json={}, headers=owner_headers()).json()
    assert session['settings']['agent_model'] == 'action-model'
    assert session['settings']['initial_context']['agent']['instructions'] == 'Read all evidence'
    assert post(client, '/items/'+item['id'], {'version':1,'active':False}).status_code == 200
    assert post(client, '/items/'+item['id'], {'version':1,'name':'Stale'}).status_code == 409
    assert action_agents.store().session(session['id'])['settings']['fleet_agent']['version'] == 1
    assert client.get(path+'/configuration').status_code == 200
    assert client.post(path+'/sessions', json={}, headers=owner_headers()).status_code == 400
    assert len(fleet.store().events(item['id'])) == 3


@pytest.mark.parametrize('bad', [{'name':''},{'active':'yes'},{'thumbnail':'../bad'}, {'skills':['missing']}, {'tools':'shell'}, {'subagents':['missing']}, {'overrides':{'arbitrary':'path'}}])
def test_validation(fleet, authenticated_client, bad):
    assert post(authenticated_client, '/items', {'name':'Agent', **bad}).status_code in {404,422}


def test_subagent_cycle_and_skill_snapshot(fleet, authenticated_client):
    client = authenticated_client
    a = post(client, '/items', {'name':'A'}).json()['item']
    b = post(client, '/items', {'name':'B','subagents':[a['id']]}).json()['item']
    assert post(client, '/items/'+a['id'], {'version':1,'subagents':[b['id']]}).status_code == 422
    upload = client.post('/agents/api/assets', files={'file':('research.md',b'# Research\nCheck sources.','text/markdown')}, headers=owner_headers()).json()
    a = post(client, '/items/'+a['id'], {'version':1,'skills':['upload:'+upload['id']]}).json()['item']
    frozen = fleet.execution(a['id'])['fleet_agent']
    assert frozen['skills'][0]['content'].endswith('Check sources.')
    assert len(frozen['skills'][0]['hash']) == 64


def test_animated_avatar_round_trip(fleet, authenticated_client):
    output = io.BytesIO()
    Image.new('RGB', (24, 24), 'red').save(output, format='GIF', save_all=True,
        append_images=[Image.new('RGB', (24, 24), 'blue')], duration=100, loop=0)
    client = authenticated_client
    uploaded = client.post('/agents/api/assets', files={'file': ('avatar.gif', output.getvalue(), 'image/gif')}, headers=owner_headers())
    assert uploaded.status_code == 200
    asset = uploaded.json()
    agent = post(client, '/items', {'name': 'Sage · Research partner', 'thumbnail': asset['id']}).json()['item']
    assert fleet.store().get(agent['id'])['thumbnail'] == asset['id']
    downloaded = client.get('/agents/api/assets/' + asset['id'])
    assert downloaded.content == output.getvalue()
    assert Image.open(io.BytesIO(downloaded.content)).n_frames == 2


def test_hud_avatars_include_all_links_and_respect_visibility(fleet, monkeypatch):
    from modules.agents.projection import hud_avatars
    from modules.second_brain import hud
    monkeypatch.setattr(hud, 'inventory', lambda: [{'operation_id': 'calendar', 'source_task': 'calendar.task'},
                                                 {'operation_id': 'unlinked', 'source_task': 'other.task'}])
    db = fleet.store()
    for identity, extra in [('sage', {'workflows': ['celery:calendar.task']}),
                            ('ada', {'triggers': ['celery:calendar.task']}),
                            ('inactive', {'active': False, 'workflows': ['celery:calendar.task']}),
                            ('private', {'connector_user': 'someone-else', 'workflows': ['celery:calendar.task']})]:
        db.save({**fleet.defaults(identity), **extra}, identity=identity)
    result = hud_avatars('owner')
    assert {a['id'] for a in result['calendar']} == {'sage', 'ada'}
    assert result['unlinked'] == []
    assert set(result['calendar'][0]) == {'id', 'name', 'runtime', 'classification', 'thumbnail', 'color'}


def test_assets_verified_and_authenticated(fleet, authenticated_client):
    client = authenticated_client
    fake = client.post('/agents/api/assets', files={'file':('bad.png',b'<script>alert(1)</script>','image/png')}, headers=owner_headers())
    assert fake.status_code == 422
    output = io.BytesIO()
    Image.new('RGB',(4,4)).save(output,format='PNG')
    result = client.post('/agents/api/assets', files={'file':('ok.png',output.getvalue(),'image/png')}, headers=owner_headers())
    assert result.status_code == 200
    identity = result.json()['id']
    assert client.get('/agents/api/assets/'+identity).content == output.getvalue()
    client.cookies.clear()
    assert client.get('/agents/api/assets/'+identity).status_code == 401


def test_csrf_and_navigation(fleet, authenticated_client):
    client = authenticated_client
    assert client.post('/agents/api/items', json={'name':'Denied'}).status_code == 403
    page = client.get('/agents')
    assert page.status_code == 200, page.text
    assert 'agent-fleet.js?v=' in page.text
    assert page.text.index('href="/agents"') < page.text.index('href="/applications"')
    assert 'Agent settings have moved' not in client.get('/settings').text


def test_prepare_retry_does_not_duplicate_actions(fleet, authenticated_client):
    one = post(authenticated_client, '/items/butler/prepare', {})
    two = post(authenticated_client, '/items/butler/prepare', {})
    assert one.status_code == 200, one.text
    assert one.json()['action_id'] == two.json()['action_id']


def test_butler_request_is_idempotent(fleet, bridge, authenticated_client, monkeypatch):
    monkeypatch.setattr(bridge[0], 'evidence_context', lambda snap: {})
    raw = {'message':'Explain the Agents page','request_id':str(uuid4()),'context':{'path':'/agents'}}
    one = post(authenticated_client, '/butler', raw)
    assert one.status_code == 200, one.text
    two = post(authenticated_client, '/butler', raw)
    assert two.json()['run_id'] == one.json()['run_id']
    assert len(bridge[1].list()) == 1
    assert post(authenticated_client, '/butler', {**raw,'message':'Different'}).status_code == 409
    history = authenticated_client.get('/agents/api/butler').json()['messages']
    assert history[0]['state'] == 'queued'
    snap = bridge[1].get(one.json()['run_id'])['snapshot']
    assert snap['execution_settings']['fleet_agent']['id'] == 'butler'
    assert not snap['auto_complete']


def test_graph_space_and_connector_scope(fleet):
    from modules.agents.projection import nodes
    fleet.initialize()
    a = fleet.store().save({**fleet.defaults('Work'), 'workspace_ids':['work']})
    fleet.store().save({**fleet.defaults('Remote'), 'runtime':'n8n', 'connector_user':'other','connector_site':'https://example.test'})
    assert [n['label'] for n in nodes(context='workspace=work')] == ['Work']
    assert 'Remote' not in {n['label'] for n in nodes()}
    assert len(nodes(query='Work')) == 1


def test_briefing_has_single_schedule_owner_and_daily_key(fleet, monkeypatch):
    from datetime import datetime
    from zoneinfo import ZoneInfo
    from modules.agents import briefings, butler
    calls = []
    monkeypatch.setattr(butler, 'send', lambda user, raw: calls.append((user,raw)))
    assert briefings.read('owner')['cadence'] == 'off'
    briefings.save('owner', {**briefings.DEFAULT,'cadence':'daily','hour':9})
    briefings.sweep(datetime(2026,10,26,8,tzinfo=ZoneInfo('Asia/Singapore')))
    assert not calls
    moment = datetime(2026,10,26,9,tzinfo=ZoneInfo('Asia/Singapore'))
    briefings.sweep(moment)
    briefings.sweep(moment)
    assert len(calls) == 2 and calls[0][1]['request_id'] == calls[1][1]['request_id']
    assert 'read-only' in calls[0][1]['message']
    with pytest.raises(ValueError):
        briefings.save('owner', {**briefings.DEFAULT,'cadence':'daily','hour':9})


def test_n8n_mcp_handshake_capability_detection_and_redaction(monkeypatch):
    import httpx
    from modules.integrations.n8n import N8n
    from fastapi import HTTPException
    client_type = httpx.Client
    methods = []
    def respond(request):
        raw=json.loads(request.content);methods.append(raw['method'])
        assert request.headers['authorization']=='Bearer mcp-secret'
        if raw['method']=='initialize':
            return httpx.Response(200,json={'result':{'protocolVersion':'2024-11-05'}},headers={'mcp-session-id':'test-session'})
        assert request.headers['mcp-session-id']=='test-session'
        if raw['method']=='notifications/initialized':
            return httpx.Response(202)
        if raw['method']=='tools/list':
            return httpx.Response(200,json={'result':{'tools':[{'name':'search_agents'}]}})
        assert raw['params']=={'name':'search_agents','arguments':{'limit':100,'query':'research'}}
        return httpx.Response(200,json={'result':{'structuredContent':{'data':[{'id':'one','name':'Research'}]}}})
    monkeypatch.setattr(httpx,'Client',lambda **kw:client_type(transport=httpx.MockTransport(respond)))
    client=N8n({'site':'https://n8n.example.test','token':'rest-secret','mcp_token':'mcp-secret'})
    assert client.agents('research')['data'][0]['name']=='Research'
    assert methods==['initialize','notifications/initialized','tools/list','tools/call']
    with pytest.raises(HTTPException) as exc:
        client.agent('one')
    assert exc.value.status_code==409
    assert 'mcp-secret' not in str(exc.value.detail)


def test_n8n_sync_preserves_local_metadata_and_disable_hides(fleet, authenticated_client, monkeypatch):
    from modules.integrations import store
    from modules.integrations.n8n import N8n
    monkeypatch.setattr(N8n, 'agents', lambda self, query='': {'data':[{'id':'remote-1','name':'External','published':True,'availableInMCP':True}]})
    user = 'frontend-test-user'
    store.save(user,'n8n',{'enabled':True,'status':'Connected','site':'https://n8n.example.test'}, {'site':'https://n8n.example.test','token':'secret'})
    url = '/integrations/api/n8n/sync'
    assert authenticated_client.post(url,json={},headers=owner_headers()).json()['imported'] == 1
    remote = next(a for a in fleet.store().list() if a['runtime']=='n8n')
    assert post(authenticated_client,'/items/'+remote['id'],{'version':remote['version'],'name':'My assistant'}).status_code == 200
    authenticated_client.post(url,json={},headers=owner_headers())
    assert fleet.store().get(remote['id'])['name'] == 'My assistant'
    assert any(a['id']==remote['id'] for a in authenticated_client.get('/agents/api/items').json()['items'])
    store.save(user,'n8n',{'enabled':False,'status':'Connected','site':'https://n8n.example.test'})
    assert not any(a['id']==remote['id'] for a in authenticated_client.get('/agents/api/items').json()['items'])


def test_fleet_browser(fleet, authenticated_client, tmp_path):
    playwright = pytest.importorskip('playwright.sync_api')
    client = authenticated_client
    fleet.initialize()
    errors=[]
    with playwright.sync_playwright() as p:
        browser=p.chromium.launch(channel='chrome', headless=True)
        page=browser.new_page(viewport={'width':1440,'height':1000})
        page.on('pageerror',lambda e:errors.append(str(e)))
        def route(r):
            u=urlparse(r.request.url)
            if u.path=='/hfl-corpus/workspace-views':
                r.fulfill(content_type='application/json',body=json.dumps({'views':[{'id':'work','name':'Work'}]}));return
            response=client.request(r.request.method,u.path+('?' + u.query if u.query else ''),content=r.request.post_data_buffer,
                                    headers={k:v for k,v in r.request.headers.items() if k.lower() in {'content-type','x-csrf-token'}})
            r.fulfill(status=response.status_code,content_type=response.headers.get('content-type','text/html'),body=response.content)
        page.route('https://fleet.test/**', route)
        page.goto('https://fleet.test/agents')
        page.get_by_role('button',name='+ Add agent').click()
        page.get_by_label('Name',exact=True).fill('Research assistant')
        page.get_by_label('Description',exact=True).fill('Investigates sources and writes evidence-backed reports.')
        page.get_by_role('button',name='Save agent',exact=True).click()
        page.get_by_role('button',name='Select Research assistant',exact=True).wait_for()
        page.get_by_role('button',name='Select Research assistant',exact=True).click()
        page.get_by_role('button',name='Deactivate',exact=True).click()
        page.locator('.fleet-filter-menu > summary').click()
        page.get_by_label('Show deactivated',exact=True).check()
        page.locator('.fleet-filter-menu > summary').click()
        page.get_by_role('button',name='Select Research assistant',exact=True).click()
        assert page.get_by_role('button',name='Open session',exact=True).is_disabled()
        page.get_by_role('button',name='Activate',exact=True).click()
        page.wait_for_timeout(1800)
        page.evaluate('window.scrollTo(0,0)')
        page.screenshot(path=str(tmp_path/'fleet-desktop.png'))
        page.set_viewport_size({'width':390,'height':844})
        page.wait_for_timeout(1000)
        page.evaluate('window.scrollTo(0,0)')
        page.screenshot(path=str(tmp_path/'fleet-mobile.png'),full_page=True)
        assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
        page.get_by_role('button',name='✧ HARQIS Butler',exact=True).click()
        page.get_by_label('Ask about your work or describe an action to prepare').wait_for()
        assert not errors, errors
        browser.close()
