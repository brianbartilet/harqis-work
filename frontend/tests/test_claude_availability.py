import json
import socket
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from frontend.tests.test_agent_fleet import fleet, bridge
from frontend.tests.test_hfl_agent_bridge import owner_headers
from modules.agents import availability, ecosystem, entities, projection
from modules.integrations import claude, store

USER = 'frontend-test-user'


@pytest.fixture
def native(fleet, monkeypatch, tmp_path):
    from modules.hfl_corpus.action_agents import store as terminals
    auth = {'loggedIn': True, 'authMethod': 'claude.ai', 'email': 'private@example.test'}
    monkeypatch.setattr(claude, 'executable', lambda runtime: '/test/claude')
    original_timeout = claude.subprocess.TimeoutExpired
    monkeypatch.setattr(claude, 'subprocess', SimpleNamespace(run=lambda *a, **kw: SimpleNamespace(returncode=0, stdout=json.dumps(auth).encode()), TimeoutExpired=original_timeout))
    root = tmp_path / 'skills'
    (root / 'review').mkdir(parents=True)
    (root / 'review/SKILL.md').write_text('---\nname: Review\ndescription: Review changes\n---\nPRIVATE BODY NOT IMPORTED', encoding='utf-8')
    monkeypatch.setattr(claude, 'skill_roots', lambda: [('project', root)])
    terminals().advertise(socket.gethostname(), [{'id': k, 'name': k.title(), 'available': True, 'reason': ''} for k in ('hermes', 'codex', 'claude')])
    return fleet, auth, terminals, root


def connect(client):
    assert client.post('/integrations/api/connectors/claude/test', json={'transport':'local'}, headers=owner_headers()).status_code == 200
    response = client.post('/integrations/api/connectors/claude/save', json={'transport':'local'}, headers=owner_headers())
    assert response.status_code == 200, response.text
    response = client.post('/integrations/api/connectors/claude/toggle', json={'enabled':True}, headers=owner_headers())
    assert response.status_code == 200, response.text


def test_claude_connect_multiple_profiles_shared_skills_and_butler(native, authenticated_client):
    fleet, _, _, _ = native
    connect(authenticated_client)
    first = next(a for a in fleet.store().list() if a['runtime'] == 'claude')
    second = claude.link(USER, {'profile': {'name': 'Claude reviewer'}})['item']
    assert second['id'] != first['id']
    data = ecosystem.graph(USER)
    connector = next(n for n in data['nodes'] if n['kind'] == 'connector' and n.get('source') == 'claude')
    skills = [n for n in data['nodes'] if n['kind'] == 'skill' and n.get('source') == 'claude']
    assert len(skills) == 1 and skills[0]['label'] == 'Review'
    assert set(skills[0]['agent_ids']) == {first['id'], second['id']}
    assert any(e['source'] == 'agent:butler' and e['target'] == connector['id'] and e['relation'] == 'monitors' for e in data['edges'])
    assert all(a['availability']['available'] for a in data['agents'] if a['runtime'] == 'claude')
    assert 'PRIVATE BODY' not in json.dumps(data) and 'private@example.test' not in json.dumps(data)
    assert not any(a['runtime'] == 'claude' for a in projection.listing('another-owner'))
    claude.refresh(USER, first['id'])
    assert len([n for n in entities.snapshot(USER)['items'] if n['kind'] == 'skill']) == 1


def test_disconnect_retains_inspectable_agents_but_blocks_selection_and_execution(native, authenticated_client):
    fleet, _, _, _ = native
    connect(authenticated_client)
    agent = next(a for a in fleet.store().list() if a['runtime'] == 'claude')
    response = authenticated_client.post('/integrations/api/connectors/claude/disconnect', json={}, headers=owner_headers())
    assert response.status_code == 200
    projected = next(a for a in projection.listing(USER) if a['id'] == agent['id'])
    assert not projected['availability']['available'] and projected['active']
    data = ecosystem.graph(USER)
    assert all(n['available'] is False for n in data['nodes'] if n.get('source') == 'claude')
    assert authenticated_client.get('/agents/api/items/' + agent['id'] + '/activity').status_code == 200
    response = authenticated_client.post('/agents/api/items/' + agent['id'] + '/prepare', json={}, headers=owner_headers())
    assert response.status_code == 409
    from modules.hfl_corpus.action_assignment import validate
    with pytest.raises(HTTPException):
        validate({'assignment_mode': 'agent', 'agent_id': agent['id']}, {}, USER)
    response = authenticated_client.post('/agents/api/items', json={'name':'Unavailable', 'runtime':'claude'}, headers=owner_headers())
    assert response.status_code == 409


def test_worker_loss_auth_failure_recovery_and_manual_deactivation(native, authenticated_client):
    fleet, auth, terminals, _ = native
    connect(authenticated_client)
    agent = next(a for a in fleet.store().list() if a['runtime'] == 'claude')
    terminals().advertise(socket.gethostname(), [{'id':'claude','name':'Claude','available':False,'reason':'Sign in on this host'}])
    assert 'Sign in' in availability.for_agent(USER, agent)['reason']
    assert not availability.connector(USER, 'claude')['available']
    terminals().advertise(socket.gethostname(), [{'id':'claude','name':'Claude','available':True,'reason':''}])
    assert availability.for_agent(USER, agent)['available']
    assert not availability.for_agent(USER, {**agent, 'active':False})['available']
    auth['loggedIn'] = False
    with pytest.raises(HTTPException):
        claude.Claude(claude.credentials({})).test()
    assert store.get(USER, 'claude')['enabled']


def test_all_provider_types_and_shared_child_availability(native, authenticated_client):
    fleet, _, _, _ = native
    connect(authenticated_client)
    claude_agent = next(a for a in fleet.store().list() if a['runtime'] == 'claude')
    # An independent healthy connection can still support a shared object.
    nod = fleet.initialize().save({**fleet.defaults('Nod'), 'runtime':'nod', 'connector_provider':'nod', 'connector_user':USER, 'connector_site':'https://nod.test'})
    store.save(USER, 'nod', {'enabled':True,'status':'Connected','site':'https://nod.test','account_id':'nod'})
    skill = next(n for n in entities.snapshot(USER)['items'] if n['kind'] == 'skill')
    entities.associate(USER, nod['id'], skill['id'], True)
    store.save(USER, 'claude', {'enabled':False,'status':'Not connected'}, {})
    assert next(n for n in ecosystem.graph(USER)['nodes'] if n['id'] == skill['id'])['available']
    for runtime in ('codex', 'claude', 'grokbot', 'n8n', 'chatgpt', 'service'):
        assert not availability.for_agent(USER, {**fleet.defaults(runtime), 'runtime':runtime})['available']
    assert availability.for_agent(USER, nod)['available']
    store.save(USER, 'nod', {'enabled':False,'status':'Connected','site':'https://nod.test','account_id':'nod'})
    assert not availability.for_agent(USER, nod)['available']


def test_failed_skill_read_preserves_last_observation(native, authenticated_client):
    fleet, _, _, root = native
    connect(authenticated_client)
    agent = next(a for a in fleet.store().list() if a['runtime'] == 'claude')
    (root/'review/SKILL.md').write_text('---\nname: [broken\n---', encoding='utf-8')
    result = claude.refresh(USER, agent['id'])
    assert result['warnings']
    assert any(n['label'] == 'Review' for n in entities.snapshot(USER)['items'])


def test_native_host_affinity_and_replaced_installation(native, authenticated_client):
    fleet, _, terminals, _ = native
    connect(authenticated_client)
    agent = next(a for a in fleet.store().list() if a['runtime'] == 'claude')
    terminals().advertise('different-host', [{'id':'claude','name':'Claude','available':True,'reason':''}])
    assert not availability.for_agent(USER, {**agent, 'overrides':{'agent_host':'different-host'}})['available']
    capabilities = authenticated_client.get('/hfl-corpus/agent-bridge/terminal-runtimes').json()
    assert not next(h for h in capabilities['hosts'] if h['host'] == 'different-host')['runtimes'][0]['available']
    store.save(USER, 'claude', {**store.get(USER, 'claude'), 'site':'replacement', 'account_id':'replacement'})
    graph = ecosystem.graph(USER)
    assert all(n['available'] is False for n in graph['nodes'] if n.get('source') == 'claude')


@pytest.mark.parametrize('width', [390, 1440])
def test_claude_card_and_unavailable_inspection_browser(native, authenticated_client, tmp_path, width):
    from urllib.parse import urlparse
    from playwright.sync_api import sync_playwright, expect
    fleet, _, _, _ = native
    with sync_playwright() as p:
        browser = p.chromium.launch(channel='chrome', headless=True)
        page = browser.new_page(viewport={'width':width,'height':1000})
        errors = []
        page.on('pageerror', lambda e: errors.append(str(e)))
        def route(r):
            u = urlparse(r.request.url)
            response = authenticated_client.request(r.request.method, u.path + ('?' + u.query if u.query else ''), content=r.request.post_data_buffer,
                headers={k:v for k,v in r.request.headers.items() if k.lower() in {'content-type','x-csrf-token'}})
            r.fulfill(status=response.status_code, content_type=response.headers.get('content-type','text/html'), body=response.content)
        page.route('https://fleet.test/**', route)
        page.goto('https://fleet.test/applications')
        card = page.locator('.connector-card').filter(has=page.get_by_role('heading', name='Claude', exact=True))
        expect(card).to_have_attribute('data-available', 'false')
        card.get_by_role('button', name='Connect', exact=True).click()
        dialog = page.get_by_role('dialog', name='Connect Claude')
        dialog.get_by_role('button', name='Test local host', exact=True).click()
        expect(dialog.get_by_role('button', name='Save and enable', exact=True)).to_be_enabled()
        dialog.get_by_role('button', name='Save and enable', exact=True).click()
        expect(dialog).not_to_be_visible()
        expect(card).to_have_attribute('data-available', 'true')
        assert card.locator('img').evaluate('e=>e.complete&&e.naturalWidth>0')
        agent = next(a for a in fleet.store().list() if a['runtime'] == 'claude')
        store.save(USER, 'claude', {'status':'Not connected','enabled':False}, {})
        page.goto('https://fleet.test/agents?agent=' + agent['id'])
        if width < 600:
            page.get_by_role('button', name='Close Agent work drawer', exact=True).click()
        expect(page.get_by_role('button', name='Open session', exact=True)).to_be_disabled()
        expect(page.get_by_role('button', name='Add action', exact=True)).to_be_disabled()
        expect(page.get_by_role('button', name='Edit', exact=True)).to_be_enabled()
        expect(page.locator('.fleet-availability-reason')).to_contain_text('Not connected')
        expect(page.locator('.fleet-map')).to_have_attribute('aria-busy', 'false', timeout=15000)
        page.screenshot(path=str(tmp_path/f'claude-offline-{width}.png'), full_page=True)
        assert not page.evaluate('document.documentElement.scrollWidth>innerWidth')
        assert not errors
        browser.close()
