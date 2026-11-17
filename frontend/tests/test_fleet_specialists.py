"""Specialist provenance, persistence, execution composition and provider boundaries."""
import pytest
from frontend.tests.test_agent_fleet import fleet, post
from frontend.tests.test_hfl_agent_bridge import bridge
from frontend.tests.test_primary_assistant import gateway, USER


def selection(client):
    row = client.get('/agents/api/specialists').json()['items'][0]
    return {key: row[key] for key in ('id', 'revision', 'hash')}


def test_catalog_detail_and_frozen_execution(fleet, authenticated_client, monkeypatch):
    client = authenticated_client
    selected = selection(client)
    detail = client.get('/agents/api/specialists/' + selected['id']).json()
    assert '<h1' in detail['html'] and detail['source_url'].startswith('https://github.com/')
    response = post(client, '/items', {'name':'Ada', 'specialist_profile':selected, 'instructions':'Focus on retries.'})
    assert response.status_code == 200, response.text
    item = response.json()['item']
    assert item['instructions'] == 'Focus on retries.'
    frozen = fleet.execution(item['id'])['fleet_agent']
    assert detail['content'] in frozen['instructions']
    assert 'Focus on retries.' in frozen['instructions']
    assert frozen['specialist_profile']['hash'] == selected['hash']
    from modules.agents import specialists
    monkeypatch.setattr(specialists, 'catalog', lambda: [])
    # A saved snapshot remains usable even if the catalog changes or removes it.
    edited = post(client, '/items/'+item['id'], {'version':item['version'], 'name':'Ada updated', 'specialist_profile':item['specialist_profile']})
    assert edited.status_code == 200, edited.text
    assert fleet.execution(item['id'])['fleet_agent']['instructions'] == frozen['instructions']
    removed = post(client, '/items/'+item['id'], {'version':2,'specialist_profile':None})
    assert removed.status_code == 200
    assert fleet.execution(item['id'])['fleet_agent']['instructions'] == 'Focus on retries.'


def test_tampered_stale_and_oversized_profiles_rejected(fleet, authenticated_client):
    client = authenticated_client
    selected = selection(client)
    for bad in [dict(selected,hash='wrong'),dict(selected,content='injected'),dict(selected,id='../escape'), 'bad']:
        assert post(client, '/items', {'name':'Bad','specialist_profile':bad}).status_code == 422
    selected = {key:value for key,value in client.get('/agents/api/specialists').json()['items'][1].items() if key in ('id','revision','hash')}
    assert post(client, '/items', {'name':'Too long','specialist_profile':selected,'instructions':'x'*20000}).status_code == 422


def test_preview_and_external_provider_metadata(fleet, authenticated_client):
    client = authenticated_client
    selected = selection(client)
    raw = {'name':'Review','runtime':'codex','specialist_profile':selected,'instructions':''}
    preview = post(client, '/specialist-preview', {'profile':raw})
    assert preview.status_code == 200, preview.text
    assert preview.json() == {'instructions':'','status':'Provider setup required'}
    item = post(client, '/items', raw).json()['item']
    assert item['specialist_profile']['id'] == selected['id']
    with pytest.raises(ValueError):
        fleet.execution(item['id'])
    assert post(client, '/items/'+item['id'], {'version':1,'instructions':'Change remote'}).status_code == 422
    raw['runtime']='hermes'
    preview = post(client, '/specialist-preview', {'profile':raw}).json()
    assert 'Code Reviewer' in preview['instructions']
    assert len(fleet.store().list()) == 4  # preview creates no agent


def test_source_hash_mismatch_fails_closed(fleet, tmp_path, monkeypatch):
    from modules.agents import specialists
    import shutil
    shutil.copytree(specialists.ROOT, tmp_path/'catalog')
    monkeypatch.setattr(specialists,'ROOT',tmp_path/'catalog')
    row = specialists.catalog()[0]
    (specialists.ROOT/'upstream'/row['path'].split('/')[-1]).write_text('changed')
    with pytest.raises(ValueError,match='integrity'):
        specialists.detail(row['id'])


def test_gateway_and_primary_conversations_freeze_specialist(gateway, fleet, authenticated_client):
    from frontend.tests.test_fleet_connections import configured, conversation
    from frontend.tests.test_primary_assistant import new
    from modules.agents import assistant
    client = authenticated_client
    item, _, _ = configured(client)
    selected = selection(client)
    updated = post(client, '/items/'+item['id'], {'version':1,'specialist_profile':selected}).json()['item']
    identity = conversation(client, updated)
    with fleet.store().connect() as db:
        frozen = assistant.read(db, USER, identity)
    assert 'Code Reviewer' in frozen['instructions']
    assert 'You have no tools' in frozen['instructions']
    assert frozen['specialist_profile']['hash'] == selected['hash']
    # The primary assistant uses the same composition and its own chat restrictions.
    result = post(client, '/assistant/primary', {'agent_id':item['id'],'version':0})
    assert result.status_code == 200, result.text
    primary = new(client)
    with fleet.store().connect() as db:
        frozen_primary = assistant.read(db,USER,primary)
    assert 'Code Reviewer' in frozen_primary['instructions']
    assert frozen_primary['specialist_profile']['revision'] == selected['revision']
    assert post(client, '/items/'+item['id'], {'version':2,'specialist_profile':None}).status_code == 200
    with fleet.store().connect() as db:
        assert assistant.read(db,USER,primary)['instructions'] == frozen_primary['instructions']


def test_specialist_routes_require_owner_and_csrf(fleet, authenticated_client):
    client = authenticated_client
    assert client.post('/agents/api/specialist-preview',json={'profile':{'name':'A'}}).status_code == 403
    client.cookies.clear()
    assert client.get('/agents/api/specialists').status_code == 401


@pytest.mark.parametrize('width', [1440, 390])
def test_picker_apply_preserve_preview_and_save(fleet, authenticated_client, tmp_path, width):
    from pathlib import Path
    from urllib.parse import urlsplit
    import json
    playwright = pytest.importorskip('playwright.sync_api')
    with playwright.sync_playwright() as engine:
        browser = engine.chromium.launch(headless=True, **({} if Path(engine.chromium.executable_path).exists() else {'channel':'msedge'}))
        context = browser.new_context(viewport={'width':width,'height':900})
        failures = [True]
        def respond(route):
            request = route.request
            url = urlsplit(request.url)
            if url.path == '/agents/api/graph':
                agents=[{**a,'state':'Ready'} for a in fleet.store().list() if a['name']=='Ada test']
                route.fulfill(json={'agents':agents, 'nodes':[{'id':'agent:'+a['id'],'agent_id':a['id'],'kind':'agent','label':a['name'],'color':a['color'],'workspace_ids':[]} for a in agents], 'edges':[], 'warnings':[], 'types':[]}); return
            if url.path == '/agents/api/assistant':
                route.fulfill(json={'agent_id':''}); return
            if url.path == '/agents/api/specialists' and failures:
                failures.pop(); route.fulfill(status=503,json={'detail':'Catalog temporarily unavailable'}); return
            response = authenticated_client.request(request.method,url.path+('?' + url.query if url.query else ''),content=request.post_data_buffer,
                headers={k:v for k,v in request.headers.items() if k.lower() in {'content-type','x-csrf-token'}})
            route.fulfill(status=response.status_code,body=response.content,headers={k:v for k,v in response.headers.items() if k.lower() not in {'content-length','content-encoding'}})
        context.route('https://fleet.test/**',respond)
        page = context.new_page()
        errors=[]
        page.on('pageerror',lambda e:errors.append(str(e)))
        page.goto('https://fleet.test/agents')
        page.get_by_role('button',name='Add agent',exact=True).click()
        page.get_by_role('button',name='Retry loading profiles').click()
        page.get_by_label('Name',exact=True).fill('Ada test')
        page.get_by_label('Classification',exact=True).select_option('coding')
        page.get_by_label('Description',exact=True).fill('My description')
        page.get_by_label('Available specialist profiles').select_option('engineering-code-reviewer')
        page.get_by_role('button',name='Use this profile').click()
        playwright.expect(page.get_by_label('Description',exact=True)).to_have_value('My description')
        page.get_by_label('Search specialist profiles').fill('no such profile')
        playwright.expect(page.get_by_text('No matching profiles.',exact=False)).to_be_visible()
        playwright.expect(page.locator('.fleet-specialist-selected')).to_contain_text('Code Reviewer')
        page.get_by_role('button',name='Preview effective instructions').click()
        playwright.expect(page.locator('.fleet-specialist-preview')).to_contain_text('Code Reviewer')
        page.locator('.fleet-specialists').scroll_into_view_if_needed()
        page.screenshot(path=str(Path('results') / f'fleet-specialist-{width}.png'))
        assert page.locator('.fleet-agent-editor').evaluate('(el)=>el.scrollWidth <= el.clientWidth + 1')
        page.get_by_role('button',name='Save agent',exact=True).click()
        playwright.expect(page.get_by_role('heading',name='Create agent',exact=True)).to_be_hidden()
        item=next(a for a in fleet.store().list() if a['name']=='Ada test')
        assert item['description']=='My description'
        assert item['specialist_profile']['id']=='engineering-code-reviewer'
        page.goto('https://fleet.test/agents?agent='+item['id'])
        page.get_by_role('button',name='Close Agent work drawer',exact=True).click()
        page.get_by_role('button',name='Edit',exact=True).click()
        playwright.expect(page.locator('.fleet-specialist-selected')).to_contain_text('Code Reviewer')
        playwright.expect(page.get_by_label('Description',exact=True)).to_have_value('My description')
        page.get_by_label('Classification',exact=True).select_option('general')
        playwright.expect(page.locator('.fleet-specialist-selected')).to_contain_text('Code Reviewer')
        page.get_by_label('Available specialist profiles').select_option('engineering-technical-writer')
        page.get_by_role('button',name='Use this profile').click()
        playwright.expect(page.get_by_label('Description',exact=True)).to_have_value('My description')
        page.get_by_role('button',name='Remove profile',exact=True).click()
        playwright.expect(page.locator('.fleet-specialist-selected')).to_have_count(0)
        playwright.expect(page.get_by_label('Description',exact=True)).to_have_value('My description')
        assert not errors
        browser.close()
