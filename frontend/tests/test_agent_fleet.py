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


def test_nod_profile_is_visible_but_cannot_execute(fleet, authenticated_client):
    client = authenticated_client
    catalogue = client.get('/agents/api/catalogue').json()
    assert {'id': 'nod', 'name': 'Nod', 'classification': 'workflows'} in catalogue['services']
    response = post(client, '/items', {'name': 'Nod · Browser assistant', 'runtime': 'nod'})
    assert response.status_code == 200, response.text
    agent = response.json()['item']
    assert agent['classification'] == 'workflows'
    listing = client.get('/agents/api/items').json()['items']
    assert next(a for a in listing if a['id'] == agent['id'])['state'] == 'Externally managed'
    with pytest.raises(ValueError):
        fleet.execution(agent['id'])
    assert post(client, '/assistant/primary', {'agent_id': agent['id'], 'version': 0}).status_code == 422
    edited = post(client, '/items/' + agent['id'], {'version': agent['version'], 'name': 'Nod · Admin', 'active': False})
    assert edited.status_code == 200
    assert edited.json()['item']['runtime'] == 'nod'


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
            response=client.request(r.request.method,u.path+('?' + u.query if u.query else ''),content=r.request.post_data_buffer,
                                    headers={k:v for k,v in r.request.headers.items() if k.lower() in {'content-type','x-csrf-token'}})
            r.fulfill(status=response.status_code,content_type=response.headers.get('content-type','text/html'),body=response.content)
        page.route('https://fleet.test/**', route)
        page.goto('https://fleet.test/agents')
        page.locator('.fleet-detail-empty').wait_for()
        assert page.locator('.fleet-hud-heading h2').inner_text()=='HARQIS Butler'
        assert page.locator('.fleet-workspace.fleet-has-selection').count()==0
        page.wait_for_function("[...document.querySelectorAll('.fleet-graph-avatars .agent-avatar')].length>1 && [...document.querySelectorAll('.fleet-graph-avatars .agent-avatar')].every(el=>Number(el.style.opacity)===1)")
        page.get_by_role('button',name='+ Add agent').click()
        page.get_by_label('Name',exact=True).fill('Research assistant')
        page.get_by_label('Description',exact=True).fill('Investigates sources and writes evidence-backed reports.')
        page.get_by_role('button',name='Save agent',exact=True).click()
        page.get_by_role('button',name='Select Research assistant',exact=True).wait_for()
        page.get_by_role('button',name='Select Research assistant',exact=True).click()
        assert page.locator('.fleet-hud-heading h2').inner_text()=='Research assistant'
        page.locator('.fleet-map canvas').click(position={'x':35,'y':35})
        page.locator('.fleet-detail-empty').wait_for()
        assert page.locator('.fleet-hud-heading h2').inner_text()=='HARQIS Butler'
        page.get_by_role('button',name='Select Research assistant',exact=True).click()
        page.get_by_role('button',name='Deactivate',exact=True).click()
        page.get_by_role('button',name='Filters',exact=True).click()
        page.get_by_label('Show deactivated',exact=True).check()
        page.get_by_role('dialog',name='Filters',exact=True).get_by_role('button',name='Close',exact=True).click()
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
        page.goto('https://fleet.test/agents?agent=butler')
        page.locator('.fleet-workspace.fleet-has-selection').wait_for()
        assert page.locator('.fleet-inspector h2').inner_text()=='HARQIS Butler'
        assert page.locator('.fleet-hud-heading h2').inner_text()=='HARQIS Butler'
        page.locator('.fleet-output-list button').first.click()
        assert page.locator('.fleet-hud-heading h2').inner_text()=='HARQIS Butler'
        assert not errors, errors
        browser.close()


@pytest.mark.parametrize('width,height', [(1440,1000),(390,844)])
def test_fleet_activity_labels_and_solid_hud_links(fleet, authenticated_client, tmp_path, width, height):
    playwright=pytest.importorskip('playwright.sync_api')
    fleet.initialize()
    errors=[]
    with playwright.sync_playwright() as p:
        browser=p.chromium.launch(channel='chrome',headless=True)
        page=browser.new_page(viewport={'width':width,'height':height})
        page.on('pageerror',lambda e:errors.append(str(e)))
        page.add_init_script("""(() => {
          window.labelPaints=[];window.dashedLinks=0;
          const text=CanvasRenderingContext2D.prototype.fillText,dash=CanvasRenderingContext2D.prototype.setLineDash;
          CanvasRenderingContext2D.prototype.fillText=function(label,x,y,...rest){
            const m=this.getTransform();window.labelPaints.push({label,font:this.font,alpha:this.globalAlpha,x:m.a*x+m.e,y:m.d*y+m.f});
            if(window.labelPaints.length>3000)window.labelPaints.splice(0,1000);
            return text.call(this,label,x,y,...rest);
          };
          CanvasRenderingContext2D.prototype.setLineDash=function(values){if(values.some(v=>v>0))window.dashedLinks++;return dash.call(this,values);};
        })();""")
        def route(r):
            u=urlparse(r.request.url)
            response=authenticated_client.request(r.request.method,u.path+('?' + u.query if u.query else ''),content=r.request.post_data_buffer,
                headers={k:v for k,v in r.request.headers.items() if k.lower() in {'content-type','x-csrf-token'}})
            r.fulfill(status=response.status_code,content_type=response.headers.get('content-type','text/html'),body=response.content)
        page.route('https://fleet.test/**',route)
        page.goto('https://fleet.test/agents')
        page.locator('.fleet-map canvas').wait_for()
        page.wait_for_function("window.labelPaints.some(p=>p.label.includes('Butler'))")
        page.wait_for_timeout(2200)
        assert page.evaluate('window.dashedLinks')==0
        assert page.evaluate("window.labelPaints.some(p=>p.font.startsWith('500 '))")
        assert page.evaluate("new Set(window.labelPaints.map(p=>p.label)).size>1")
        assert '?v=' in page.locator('script[src*="agent-fleet.js"]').get_attribute('src')
        assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
        page.screenshot(path=str(tmp_path/f'fleet-labels-{width}.png'),full_page=True)
        # The default view is unselected; verify passive animation repaints labels.
        page.locator('.fleet-detail-empty').wait_for()
        assert page.locator('.fleet-list .agent-avatar').count()==page.locator('.fleet-list button').count()
        assert page.locator('.fleet-list .agent-avatar[tabindex]').count()==0
        assert page.locator('.fleet-detail-empty h2').evaluate("el=>getComputedStyle(el).fontSize")=='12px'
        page.locator('.fleet-inspector').screenshot(path=str(tmp_path/f'fleet-sidebar-{width}.png'))
        page.get_by_role('button',name='Animation',exact=True).click()
        page.get_by_role('button',name='Drift',exact=True).click()
        page.get_by_role('button',name='Animation',exact=True).click()
        page.mouse.move(0,0)
        page.wait_for_timeout(600)
        page.evaluate('window.labelPaints=[]')
        page.wait_for_timeout(1100)
        assert page.evaluate("new Set(window.labelPaints.filter(p=>p.label.includes('Butler')).map(p=>p.x.toFixed(2)+':'+p.y.toFixed(2))).size>5")
        # Switching off must ease back to rest, even after the force engine cooled.
        page.get_by_role('button',name='Animation',exact=True).click()
        page.get_by_role('button',name='Off',exact=True).click()
        page.get_by_role('button',name='Animation',exact=True).click()
        page.wait_for_timeout(1800)
        page.evaluate('window.labelPaints=[]')
        page.wait_for_timeout(500)
        assert page.evaluate("(() => {const points=window.labelPaints.filter(p=>p.label.includes('Butler'));return points.length<2||Math.max(...points.map(p=>p.x))-Math.min(...points.map(p=>p.x))<.2;})()")
        assert not errors,errors
        browser.close()


@pytest.mark.parametrize('width,height', [(1440,1000),(390,844)])
def test_fleet_inspector_controls_and_hud_navigation(fleet, authenticated_client, tmp_path, width, height):
    playwright=pytest.importorskip('playwright.sync_api')
    fleet.initialize()
    graph=authenticated_client.get('/agents/api/graph').json()
    anchor=next(n for n in graph['nodes'] if n['id']=='agent:butler')
    records=[dict(id='hud:'+name,kind='hud',label=name.title()+' HUD',agent_ids=['butler'],color='#e9c96c') for name in ['top','bottom','hidden']]
    records += [dict(id='action:recorded',kind='action',label='Recorded action',agent_ids=['butler'],color='#ff99aa',url='/hfl-corpus/actions?integration_agent=item-recorded')]
    graph['nodes']=[anchor,*records]
    graph['edges']=[dict(source='agent:butler',target=n['id'],relation='monitors' if n['kind']=='hud' else 'produced') for n in records]
    hud={'layout':{'widgets':[dict(id=name,operation=name,size='2x4',hidden=name=='hidden',animation='static',workspace_ids=[]) for name in ['top','bottom','hidden']]},'items':{},'agents':{},'spaces':{'views':[]}}
    errors=[]
    with playwright.sync_playwright() as p:
        browser=p.chromium.launch(channel='chrome',headless=True)
        page=browser.new_page(viewport={'width':width,'height':height},reduced_motion='reduce')
        page.on('pageerror',lambda error:errors.append(str(error)))
        def route(r):
            u=urlparse(r.request.url)
            if u.path in ['/agents/api/graph','/agents/hud/data']:
                r.fulfill(content_type='application/json',body=json.dumps(graph if u.path.endswith('/graph') else hud));return
            response=authenticated_client.request(r.request.method,u.path+('?' + u.query if u.query else ''),content=r.request.post_data_buffer,
                headers={k:v for k,v in r.request.headers.items() if k.lower() in {'content-type','x-csrf-token'}})
            r.fulfill(status=response.status_code,content_type=response.headers.get('content-type','text/html'),body=response.content)
        page.route('https://fleet.test/**',route)
        page.goto('https://fleet.test/agents?agent=butler')
        controls=page.get_by_role('group',name='Agent controls')
        controls.wait_for()
        assert controls.get_by_role('button',name='Deactivate',exact=True).is_disabled()
        for label in ['Open session','Chat with HARQIS Butler','Edit','Deactivate']:
            assert controls.get_by_role('button',name=label,exact=True).locator('svg').count()==1
            assert controls.get_by_role('button',name=label,exact=True).locator('svg').evaluate('el=>el.getBoundingClientRect().width')==18
        assert page.get_by_role('button',name='Primary assistant',exact=True).count()==0
        assert page.get_by_role('button',name='Make primary assistant',exact=True).count()==0
        assert page.get_by_label('Agent list',exact=True).count()==0
        tabs=page.get_by_role('tablist',name='Agent details')
        tabs.get_by_role('tab',name='Outputs').focus()
        page.keyboard.press('ArrowRight')
        assert tabs.get_by_role('tab',name='Profile',exact=True).get_attribute('aria-selected')=='true'
        page.keyboard.press('ArrowRight')
        assert tabs.get_by_role('tab',name='Conversation',exact=True).get_attribute('aria-selected')=='true'
        expand=page.get_by_role('button',name='Expand',exact=True)
        expand.click()
        page.locator('.fleet-conversation-expanded').wait_for()
        page.keyboard.press('Escape')
        assert expand.evaluate('el=>el===document.activeElement')
        positions=tabs.get_by_role('tab').evaluate_all('els=>els.map(el=>el.getBoundingClientRect().top)')
        assert len(set(positions))==1
        assert page.evaluate('document.documentElement.scrollWidth<=innerWidth')
        page.locator('.fleet-inspector').evaluate('el=>el.scrollTop=300')
        page.screenshot(path=str(tmp_path/f'inspector-{width}.png'),full_page=True)
        tabs.get_by_role('tab',name='Outputs').click()
        page.locator('.fleet-output-list button').filter(has_text='Bottom HUD').click()
        assert page.get_by_label('Agent list',exact=True).count()==0
        row=page.locator('.fleet-relationship-list').get_by_role('button',name='Select HARQIS Butler',exact=True)
        assert row.locator('.agent-avatar').count()==1
        page.get_by_role('button',name='View',exact=True).click()
        card=page.locator('.fleet-hud-card[data-id="hud:bottom"]')
        assert card.evaluate('el=>el===document.activeElement')
        assert page.locator('.fleet-hud-panel').evaluate('el=>el.scrollTop>0')
        panel_bounds=page.locator('.fleet-hud-panel').bounding_box()
        heading_bounds=page.locator('.fleet-hud-heading').bounding_box()
        assert panel_bounds['y']<=heading_bounds['y']<=panel_bounds['y']+12
        page.locator('.fleet-hud-panel').screenshot(path=str(tmp_path/f'hud-scrolled-{width}.png'))
        row.click()
        page.locator('.fleet-output-list button').filter(has_text='Hidden HUD').click()
        page.get_by_role('button',name='View',exact=True).click()
        page.get_by_text('Not available in the current HUD view',exact=True).wait_for()
        assert page.locator('.fleet-hud-card[data-id="hud:hidden"]').count()==0
        page.locator('.fleet-relationship-list button').click()
        page.locator('.fleet-output-list button').filter(has_text='Recorded action').click()
        link=page.get_by_role('link',name='Open action',exact=True)
        assert 'edit=item-recorded' in link.get_attribute('href')
        assert 'edit_kind=actionable' in link.get_attribute('href')
        assert 'integration_agent' not in link.get_attribute('href')
        assert not errors,errors
        browser.close()


@pytest.mark.parametrize('path,width,height',[('/agents',1440,1000),('/home',1440,1000),('/home',390,844)])
def test_briefings_available_from_shared_butler(fleet, authenticated_client, tmp_path, path, width, height):
    playwright=pytest.importorskip('playwright.sync_api')
    fleet.initialize()
    schedule={'cadence':'off','hour':9,'weekday':0,'timezone':'Asia/Singapore'}
    saved=[]
    errors=[]
    with playwright.sync_playwright() as p:
        browser=p.chromium.launch(channel='chrome',headless=True)
        page=browser.new_page(viewport={'width':width,'height':height})
        page.on('pageerror',lambda error:errors.append(str(error)))
        def route(r):
            u=urlparse(r.request.url)
            if u.path=='/agents/api/butler/schedule':
                if r.request.method=='POST':
                    assert r.request.headers.get('x-csrf-token')
                    saved.append(r.request.post_data_json)
                    if len(saved)==1:
                        r.fulfill(status=503,content_type='application/json',body=json.dumps({'detail':'Try again'}));return
                    schedule.update(saved[-1])
                r.fulfill(content_type='application/json',body=json.dumps(schedule));return
            response=authenticated_client.request(r.request.method,u.path+('?' + u.query if u.query else ''),content=r.request.post_data_buffer,
                headers={k:v for k,v in r.request.headers.items() if k.lower() in {'content-type','x-csrf-token'}})
            r.fulfill(status=response.status_code,content_type=response.headers.get('content-type','text/html'),body=response.content)
        page.route('https://fleet.test/**',route)
        page.goto('https://fleet.test'+path)
        assert page.locator('.fleet-toolbar').get_by_role('button',name='Briefings',exact=True).count()==0
        page.locator('#butler-launch').click()
        trigger=page.get_by_role('button',name='Automatic briefings',exact=True)
        assert trigger.locator('svg').count()==1
        trigger.click()
        assert not errors,errors
        page.screenshot(path=str(tmp_path/'briefings-open.png'),full_page=True)
        dialog=page.get_by_role('dialog',name='Automatic briefings',exact=True)
        assert dialog.count()==1,page.locator('#butler-briefings').evaluate('el=>({open:el.open,html:el.outerHTML})')
        dialog.get_by_label('Frequency',exact=True).select_option('weekly')
        dialog.get_by_label('Day',exact=True).select_option('4')
        dialog.get_by_label('Hour (0–23)',exact=True).fill('15')
        bounds=dialog.bounding_box()
        assert abs(bounds['x']+bounds['width']/2-width/2)<2
        assert abs(bounds['y']+bounds['height']/2-height/2)<2
        page.screenshot(path=str(tmp_path/'briefings.png'),full_page=True)
        dialog.get_by_role('button',name='Save schedule',exact=True).click()
        dialog.get_by_text('Try again',exact=True).wait_for()
        dialog.get_by_role('button',name='Save schedule',exact=True).click()
        dialog.wait_for(state='hidden')
        assert trigger.evaluate('el=>el===document.activeElement')
        assert schedule=={'cadence':'weekly','hour':15,'weekday':4,'timezone':'Asia/Singapore'}
        trigger.click()
        page.wait_for_function("document.getElementById('butler-briefings-cadence').value==='weekly' && !document.getElementById('butler-briefings-fields').disabled")
        page.keyboard.press('Escape')
        dialog.wait_for(state='hidden')
        assert page.locator('#butler-panel').is_visible()
        assert trigger.evaluate('el=>el===document.activeElement')
        assert not errors,errors
        browser.close()
