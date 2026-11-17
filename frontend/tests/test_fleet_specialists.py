"""Specialist provenance, persistence, execution composition and provider boundaries."""
import pytest
from frontend.tests.test_agent_fleet import fleet, post
from frontend.tests.test_hfl_agent_bridge import bridge
from frontend.tests.test_primary_assistant import gateway, USER


@pytest.fixture(autouse=True)
def catalog_data(fleet, monkeypatch):
    """Keep catalog/API tests offline; bytes and hashes agree in the isolated index."""
    import json
    from modules.agents import profile_sources as sources
    sources.seed()
    downloads={}
    with fleet.store().connect() as db:
        for record in db.execute('SELECT * FROM fleet_profile_index').fetchall():
            row=json.loads(record['payload'])
            content=('# '+row['name']+'\nCheck evidence.\n'+('Long guidance. '*2300 if row['slug']=='healthcare-marketing-compliance' else '')).encode()
            row['hash']=sources.sha(content)
            downloads[row['download_url']]=content
            db.execute('UPDATE fleet_profile_index SET payload=? WHERE id=?',(json.dumps(row),row['id']))
    calls=[]
    def fetch(url, maximum=sources.MAX_FILE):
        calls.append(url)
        if url not in downloads:
            raise ValueError('Test download unavailable.')
        value=downloads[url]
        if isinstance(value,Exception):
            raise value
        assert len(value)<=maximum
        return value
    monkeypatch.setattr(sources,'download',fetch)
    return downloads,calls


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
    assert post(client, '/items', {'name':'Too long','specialist_profile':selected,'instructions':'x'*20001}).status_code == 422


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


def test_source_hash_mismatch_fails_closed(fleet, catalog_data):
    from modules.agents import specialists
    row = specialists.catalog()[0]
    catalog_data[0][row['download_url']]=b'changed'
    with pytest.raises(ValueError,match='integrity'):
        specialists.detail(row['id'])


def test_gateway_and_primary_conversations_freeze_specialist(gateway, fleet, authenticated_client):
    from frontend.tests.test_fleet_connections import configured, conversation
    from frontend.tests.test_primary_assistant import new
    from modules.agents import assistant
    client = authenticated_client
    item, _, _ = configured(client)
    row = next(row for row in client.get('/agents/api/specialists').json()['items'] if row['id']=='agency-agents:healthcare-marketing-compliance')
    selected = {key:row[key] for key in ('id','revision','hash')}
    body = client.get('/agents/api/specialists/'+row['id']).json()['content']
    assert len(body) > 28000
    updated = post(client, '/items/'+item['id'], {'version':1,'specialist_profile':selected}).json()['item']
    identity = conversation(client, updated)
    with fleet.store().connect() as db:
        frozen = assistant.read(db, USER, identity)
    assert body in frozen['instructions']
    assert 'You have no tools' in frozen['instructions']
    assert frozen['specialist_profile']['hash'] == selected['hash']
    # The primary assistant uses the same composition and its own chat restrictions.
    result = post(client, '/assistant/primary', {'agent_id':item['id'],'version':0})
    assert result.status_code == 200, result.text
    primary = new(client)
    with fleet.store().connect() as db:
        frozen_primary = assistant.read(db,USER,primary)
    assert body in frozen_primary['instructions']
    assert frozen_primary['specialist_profile']['revision'] == selected['revision']
    assert post(client, '/items/'+item['id'], {'version':2,'specialist_profile':None}).status_code == 200
    with fleet.store().connect() as db:
        assert assistant.read(db,USER,primary)['instructions'] == frozen_primary['instructions']


def test_specialist_routes_require_owner_and_csrf(fleet, authenticated_client):
    client = authenticated_client
    assert client.post('/agents/api/specialist-preview',json={'profile':{'name':'A'}}).status_code == 403
    client.cookies.clear()
    assert client.get('/agents/api/specialists').status_code == 401


def test_full_catalog_integrity_and_complete_instructions(fleet, authenticated_client):
    from modules.agents import specialists
    rows = authenticated_client.get('/agents/api/specialists').json()['items']
    assert len(rows) == 283
    assert len({row['division'] for row in rows}) == 18
    assert len({row['id'] for row in rows}) == len(rows)
    assert all('content' not in row and 'html' not in row for row in rows)
    longest = None
    for row in rows:
        profile = specialists.snapshot({k:row[k] for k in ('id','revision','hash')})
        if longest is None or len(profile['content']) > len(longest['content']):
            longest = profile
        agent = {**fleet.defaults('Catalog test'),'specialist_profile':profile,'instructions':'Owner-specific guidance.'}
        composed = specialists.compose(agent)
        assert profile['content'] in composed
        assert composed.endswith('Owner-specific guidance.')
    assert len(longest['content']) > 28000
    message = specialists.conversation_instructions('You have no tools.',
        {**fleet.defaults('Long profile'),'specialist_profile':longest,'instructions':'Final owner instruction.'})
    assert longest['content'] in message
    assert message.endswith('Final owner instruction.')
    with pytest.raises(ValueError,match='56,000'):
        specialists.compose({**fleet.defaults('Too long'),'specialist_profile':longest,'instructions':'x'*56000})


def test_save_profile_from_every_division(fleet, authenticated_client):
    client = authenticated_client
    divisions = {}
    for row in client.get('/agents/api/specialists').json()['items']:
        divisions.setdefault(row['division'],row)
    for division,row in divisions.items():
        response = post(client,'/items',{'name':division+' specialist','specialist_profile':{k:row[k] for k in ('id','revision','hash')}})
        assert response.status_code == 200, response.text
        item = response.json()['item']
        assert fleet.execution(item['id'])['fleet_agent']['specialist_profile']['id'] == row['id']


def test_archive_import_is_bounded_and_reproducible(tmp_path):
    import hashlib, json, zipfile
    from tools.agency_catalog import import_catalog
    revision='a'*40
    prefix='agency-agents-'+revision+'/'
    archive=tmp_path/'source.zip'
    target=tmp_path/'catalog'
    target.mkdir()
    (target/'helpers.json').write_text('{}')
    body=b'---\nname: Example\ndescription: Test specialist\n---\n# Instructions\nRead evidence.\n'
    with zipfile.ZipFile(archive,'w') as source:
        source.writestr(prefix+'divisions.json',json.dumps({'divisions':{'testing':{'label':'Testing'}}}))
        source.writestr(prefix+'testing/example.md',body)
        source.writestr(prefix+'strategy/not-an-agent.md',body)
        source.writestr(prefix+'LICENSE','MIT test notice')
    assert import_catalog(archive,revision,target)==1
    first=(target/'manifest.json').read_bytes()
    assert import_catalog(archive,revision,target)==1
    assert first==(target/'manifest.json').read_bytes()
    assert json.loads(first)['profiles'][0]['hash']==hashlib.sha256(body).hexdigest()
    assert not (target/'upstream').exists()
    with zipfile.ZipFile(archive,'a') as source:
        source.writestr(prefix+'testing/nested/example.md',body)
    with pytest.raises(ValueError,match='duplicate'):
        import_catalog(archive,revision,target)
    assert first==(target/'manifest.json').read_bytes()


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
        page.get_by_text('Profile sources',exact=True).click()
        page.get_by_role('button',name='Add profile source',exact=True).click()
        page.get_by_label('Source name',exact=True).fill('Test team')
        page.get_by_label('Source location',exact=True).fill('example/team-profiles')
        page.get_by_role('button',name='Save profile source',exact=True).click()
        playwright.expect(page.get_by_role('button',name='Settings for Test team',exact=True)).to_be_visible()
        page.get_by_role('button',name='Disable Test team',exact=True).click()
        playwright.expect(page.get_by_role('button',name='Enable Test team',exact=True)).to_be_visible()
        page.get_by_role('button',name='Remove Test team',exact=True).click()
        playwright.expect(page.get_by_role('button',name='Settings for Test team',exact=True)).to_have_count(0)
        page.get_by_text('Profile sources',exact=True).click()
        playwright.expect(page.get_by_text('283 profiles available',exact=False)).to_be_visible()
        playwright.expect(page.locator('.fleet-specialist-results button')).to_have_count(30)
        page.get_by_role('button',name='Show more profiles').click()
        playwright.expect(page.locator('.fleet-specialist-results button')).to_have_count(60)
        page.get_by_label('Specialist division').select_option('Marketing')
        playwright.expect(page.locator('.fleet-specialist-results button').first).to_contain_text('Marketing')
        page.locator('.fleet-specialist-results button').first.click()
        playwright.expect(page.locator('.fleet-specialist-detail')).to_contain_text('No HARQIS-specific helper')
        page.get_by_label('Specialist division').select_option('')
        page.get_by_label('Name',exact=True).fill('Ada test')
        page.get_by_label('Description',exact=True).fill('My description')
        # Default General purpose must not hide coding specialists from search.
        page.get_by_label('Search specialist profiles').fill('reviewer')
        playwright.expect(page.get_by_role('button',name='Preview Code Reviewer',exact=True)).to_be_visible()
        page.get_by_role('button',name='Preview Code Reviewer',exact=True).click()
        page.get_by_role('button',name='Use this profile').click()
        playwright.expect(page.get_by_label('Description',exact=True)).to_have_value('My description')
        page.get_by_label('Search specialist profiles').fill('no such profile')
        playwright.expect(page.get_by_text('No matching profiles.',exact=False)).to_be_visible()
        playwright.expect(page.locator('.fleet-specialists > .fleet-specialist-selected')).to_contain_text('Code Reviewer')
        page.get_by_role('button',name='Preview effective instructions').click()
        playwright.expect(page.locator('.fleet-specialist-preview')).to_contain_text('Code Reviewer')
        page.locator('.fleet-specialists').scroll_into_view_if_needed()
        page.screenshot(path=str(Path('results') / f'fleet-specialist-{width}.png'))
        assert page.locator('.fleet-agent-editor').evaluate('(el)=>el.scrollWidth <= el.clientWidth + 1')
        page.get_by_role('button',name='Save agent',exact=True).click()
        playwright.expect(page.get_by_role('heading',name='Create agent',exact=True)).to_be_hidden()
        item=next(a for a in fleet.store().list() if a['name']=='Ada test')
        assert item['description']=='My description'
        assert item['specialist_profile']['id']=='agency-agents:engineering-code-reviewer'
        page.goto('https://fleet.test/agents?agent='+item['id'])
        page.get_by_role('button',name='Close Agent work drawer',exact=True).click()
        page.get_by_role('button',name='Edit',exact=True).click()
        playwright.expect(page.locator('.fleet-specialists > .fleet-specialist-selected')).to_contain_text('Code Reviewer')
        playwright.expect(page.get_by_label('Description',exact=True)).to_have_value('My description')
        page.get_by_label('Classification',exact=True).select_option('general')
        playwright.expect(page.locator('.fleet-specialists > .fleet-specialist-selected')).to_contain_text('Code Reviewer')
        page.get_by_label('Search specialist profiles').fill('Technical Writer')
        page.get_by_role('button',name='Preview Technical Writer',exact=True).click()
        page.get_by_role('button',name='Use this profile').click()
        playwright.expect(page.get_by_label('Description',exact=True)).to_have_value('My description')
        page.get_by_role('button',name='Remove profile',exact=True).click()
        playwright.expect(page.locator('.fleet-specialists > .fleet-specialist-selected')).to_have_count(0)
        playwright.expect(page.get_by_label('Description',exact=True)).to_have_value('My description')
        assert not errors
        browser.close()
