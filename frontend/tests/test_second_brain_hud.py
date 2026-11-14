import pytest
from fastapi.testclient import TestClient
from modules.hfl_shares.security import make_csrf_token
from modules.second_brain import hud, agent_hud

read_projections = hud.projections


@pytest.fixture(autouse=True)
def isolated_hud(monkeypatch):
    from modules.hfl_corpus.graph_views import connection
    from modules.hfl_corpus import workspace_views
    with connection() as db:
        agent_hud.schema(db)
        db.execute('DELETE FROM agent_hud_layout')
        workspace_views.schema(db)
        db.execute('DELETE FROM second_brain_hud_layout')
        db.execute('DELETE FROM corpus_view_preferences')
        db.execute('DELETE FROM corpus_workspace_views')
        db.execute('DELETE FROM corpus_view_schedules')
    monkeypatch.setattr(hud, 'projections', lambda: ({}, ''))


def headers():
    return {'X-CSRF-Token': make_csrf_token('frontend-test-user')}


def test_accent_palette_persists_and_rejects_unknown_colors(authenticated_client):
    payload = hud.defaults()
    payload['widgets'][0]['accent'] = hud.PIN_COLORS[0]
    saved = authenticated_client.put('/second-brain/hud/layout', json=payload, headers=headers())
    assert saved.status_code == 200
    assert hud.layout()['widgets'][0]['accent'] == hud.PIN_COLORS[0]
    payload = saved.json()
    payload['widgets'][0]['accent'] = 'url(https://example.test)'
    assert authenticated_client.put('/second-brain/hud/layout', json=payload, headers=headers()).status_code == 422
    payload['widgets'][0]['accent'] = ''
    assert authenticated_client.put('/second-brain/hud/layout', json=payload, headers=headers()).status_code == 200


def test_hud_requires_owner_and_csrf(authenticated_client):
    from main import app
    with TestClient(app) as anonymous:
        assert anonymous.get('/second-brain', follow_redirects=False).status_code == 302
        assert anonymous.get('/second-brain/hud/data').status_code == 401
    assert authenticated_client.put('/second-brain/hud/layout', json=hud.defaults()).status_code == 403


def test_hud_page_and_complete_catalog(authenticated_client):
    page = authenticated_client.get('/second-brain')
    assert page.status_code == 200
    assert 'hud-grid' in page.text
    assert 'value="1x3"' in page.text
    assert 'value="3x1"' in page.text
    assert '/static/js/second-brain-hud.js?v=' in page.text
    assert '/static/css/second-brain-hud.css?v=' in page.text
    assert 'Build with agent' in page.text
    catalog = hud.inventory()
    assert len([item for item in catalog if item['source_task']]) == 18
    assert next(item for item in catalog if item['operation_id'] == 'hud.hud_calendar.show_calendar_information')['schedules']


@pytest.mark.parametrize('size', ['1x4', '1x3', '3x1'])
def test_layout_roundtrip_and_stale_revision(authenticated_client, size):
    client = authenticated_client
    original = client.get('/second-brain/hud/data').json()['layout']
    original['widgets'][0].update(size=size, animation='typing', hidden=True)
    saved = client.put('/second-brain/hud/layout', json=original, headers=headers())
    assert saved.status_code == 200
    assert saved.json()['revision'] == 1
    assert client.get('/second-brain/hud/data').json()['layout'] == saved.json()
    assert client.put('/second-brain/hud/layout', json=original, headers=headers()).status_code == 409


@pytest.mark.parametrize('patch', [ {'size':'6x4'}, {'operation':'os.system'}, {'animation':'script'}, {'id':'<script>'} ])
def test_invalid_layout_rejected(authenticated_client, patch):
    payload = hud.defaults()
    payload['widgets'][0].update(patch)
    assert authenticated_client.put('/second-brain/hud/layout', json=payload, headers=headers()).status_code == 422


def test_duplicate_ids_and_unknown_space_rejected(authenticated_client):
    payload = hud.defaults()
    payload['widgets'].append(payload['widgets'][0])
    assert authenticated_client.put('/second-brain/hud/layout', json=payload, headers=headers()).status_code == 422
    payload = hud.defaults()
    payload['widgets'][0]['workspace_ids'] = ['removed-space']
    assert authenticated_client.put('/second-brain/hud/layout', json=payload, headers=headers()).status_code == 409


def test_shared_space_selection_and_widget_membership(authenticated_client):
    from modules.hfl_corpus import workspace_views as ws
    view = ws.save(ws.WorkspaceWrite(name='Work', state=ws.WorkspaceState()))
    state = ws.listing()
    ws.save_preferences(ws.ViewPreferences(**{**state['preferences'], 'manual':[view['id']]}))
    payload = hud.defaults()
    payload['widgets'][0]['workspace_ids'] = [view['id']]
    assert authenticated_client.put('/second-brain/hud/layout', json=payload, headers=headers()).status_code == 200
    data = authenticated_client.get('/second-brain/hud/data').json()
    assert data['spaces']['active'] == [view['id']]
    assert data['layout']['widgets'][0]['workspace_ids'] == [view['id']]


def test_projection_redaction_and_missing_source(authenticated_client, monkeypatch):
    from workflows.second_brain.models import isoformat
    task = 'workflows.hud.tasks.hud_logs.get_failed_jobs'
    monkeypatch.setattr(hud, 'projections', lambda: ({task: {'captured_at':isoformat(), 'payload':{'text':'password=supersecret\nCaptured output', 'links':{'bad':'javascript:alert(1)'}}}}, ''))
    result = authenticated_client.get('/second-brain/hud/data').json()
    item = result['items']['hud.hud_logs.get_failed_jobs'][0]
    assert 'supersecret' not in item['details']
    assert item['status'] == 'fresh'
    assert item['links'] == {}
    assert result['items']['hud.hud_calendar.show_calendar_information'][0]['status'] == 'awaiting_source'


def test_kibana_origin_is_bounded(monkeypatch):
    monkeypatch.setenv('KIBANA_HOST', 'https://monitor.example.test')
    with pytest.raises(ValueError):
        hud.Widget(id='test', operation='monitoring', dashboard_url='https://evil.test/app/dashboards')
    assert hud.Widget(id='test', operation='monitoring', dashboard_url='https://monitor.example.test/app/dashboards#/view/id').dashboard_url


def test_builder_context_has_skill_provenance(authenticated_client):
    payload = authenticated_client.get('/second-brain/hud/build-context').json()
    assert {s['name'] for s in payload['skills']} == {'create-new-hud','create-new-service-app','create-new-workflow'}
    assert all(len(s['sha256']) == 64 for s in payload['skills'])


def test_projection_read_without_optional_backfill_index(monkeypatch):
    from core.apps.es_logging.app import elasticsearch
    source = 'workflows.hud.tasks.hud_logs.get_failed_jobs'
    def read(index, **kwargs):
        if index.endswith('-migration'):
            raise RuntimeError('Search failed (404): index_not_found_exception')
        return [{'source_task':source, 'captured_at':'2026-10-24T00:00:00Z', 'payload':{'text':'latest'}}]
    monkeypatch.setattr(elasticsearch, 'get_index_data', read)
    monkeypatch.setattr(hud, '_projection_cache', {'until':0, 'items':{}, 'error':''})
    sources, error = read_projections()
    assert sources[source]['payload']['text'] == 'latest'
    assert not error


def test_agent_panel_preference_roundtrip_and_legacy_save(authenticated_client):
    client = authenticated_client
    initial = hud.layout()
    assert initial['agent_panel_expanded'] is False
    initial['agent_panel_expanded'] = True
    saved = client.put('/second-brain/hud/layout', json=initial, headers=headers())
    assert saved.status_code == 200
    assert hud.layout()['agent_panel_expanded'] is True
    # Second Brain's widget-only saves must retain the Agents panel preference.
    payload = saved.json()
    payload.pop('agent_panel_expanded')
    payload['widgets'][0]['size'] = '2x2'
    updated = client.put('/second-brain/hud/layout', json=payload, headers=headers())
    assert updated.status_code == 200
    assert updated.json()['agent_panel_expanded'] is True
    payload = updated.json()
    payload['agent_panel_expanded'] = False
    assert client.put('/second-brain/hud/layout', json=payload, headers=headers()).status_code == 200
    assert hud.layout()['agent_panel_expanded'] is False


def test_legacy_widget_array_layout_remains_readable():
    import json
    from modules.hfl_corpus.graph_views import connection
    widgets = hud.defaults()['widgets']
    with connection() as db:
        db.execute('INSERT INTO second_brain_hud_layout VALUES (1,?,?)', (1, json.dumps(widgets)))
    assert hud.layout() == {'revision': 1, 'widgets': widgets, 'agent_panel_expanded': False}


def test_agent_hud_only_syncs_spaces_in_both_directions(authenticated_client):
    from modules.hfl_corpus import workspace_views as ws
    client = authenticated_client
    space = ws.save(ws.WorkspaceWrite(name='Shared HUD Space', state=ws.WorkspaceState()))
    original = hud.layout()
    agents = client.get('/agents/hud/layout').json()
    agents['agent_panel_expanded'] = True
    agents['widgets'][0].update(size='1x1', accent='#3b82f6', animation='typing', workspace_ids=[space['id']], hidden=True)
    result = client.put('/agents/hud/layout', json=agents, headers=headers())
    assert result.status_code == 200
    second_brain = hud.layout()
    assert second_brain['widgets'][0] == {**original['widgets'][0], 'workspace_ids':[space['id']]}
    assert second_brain['agent_panel_expanded'] is False
    # A later Second Brain presentation change must not change the Agents copy.
    second_brain['widgets'][0].update(size='2x4', accent='#f97316', animation='marquee', workspace_ids=[])
    assert client.put('/second-brain/hud/layout', json=second_brain, headers=headers()).status_code == 200
    reloaded = client.get('/agents/hud/layout').json()
    widget = reloaded['widgets'][0]
    assert (widget['size'], widget['accent'], widget['animation'], widget['hidden']) == ('1x1', '#3b82f6', 'typing', True)
    assert widget['workspace_ids'] == []
    assert reloaded['agent_panel_expanded'] is True
    # Agent-only removal cannot remove the Second Brain widget.
    reloaded['widgets'].pop(0)
    assert client.put('/agents/hud/layout', json=reloaded, headers=headers()).status_code == 200
    assert len(hud.layout()['widgets']) == len(original['widgets'])


def test_agent_hud_requires_auth_csrf_and_rejects_stale_shared_revision(authenticated_client):
    from main import app
    client = authenticated_client
    with TestClient(app) as anonymous:
        assert anonymous.get('/agents/hud/layout').status_code == 401
        assert anonymous.get('/agents/hud/data').status_code == 401
    initial = client.get('/agents/hud/layout').json()
    assert client.put('/agents/hud/layout', json=initial).status_code == 403
    shared = hud.layout()
    shared['widgets'][0]['workspace_ids'] = []
    assert client.put('/second-brain/hud/layout', json=shared, headers=headers()).status_code == 200
    initial['widgets'][0]['accent'] = '#3b82f6'
    assert client.put('/agents/hud/layout', json=initial, headers=headers()).status_code == 409
    assert agent_hud.layout()['widgets'][0]['accent'] == ''


@pytest.mark.parametrize('width', [1440, 390])
def test_workspace_dashboard_navigation_and_space_sync(authenticated_client, tmp_path, width):
    import json
    from pathlib import Path
    from urllib.parse import urlsplit
    from modules.hfl_corpus import workspace_views as ws
    playwright = pytest.importorskip('playwright.sync_api')
    view = ws.save(ws.WorkspaceWrite(name='Work', state=ws.WorkspaceState()))
    ws.save_preferences(ws.ViewPreferences(**{**ws.listing()['preferences'], 'manual': [], 'dynamic': False}))
    agent = dict(id='butler', name='HARQIS Butler', runtime='hermes', active=True,
                 state='ready', classification='general', workspace_ids=[], workflows=[],
                 triggers=[], skills=[], tools=[], subagents=[], color='#3b82f6')
    graph = dict(agents=[agent], nodes=[dict(id='agent:butler', agent_id='butler',
                 kind='agent', label='HARQIS Butler', color='#3b82f6', workspace_ids=[])],
                 edges=[], warnings=[], types=[dict(id='agent', name='Agent', color='#3b82f6')])
    failures = [True]
    hud_reads = []
    held_graph = []
    hold_graph = [True]
    held_dashboard = []
    hold_dashboard = []
    with playwright.sync_playwright() as engine:
        options = dict(headless=True)
        if not Path(engine.chromium.executable_path).exists():
            options['channel'] = 'msedge'
        browser = engine.chromium.launch(**options)
        context = browser.new_context(viewport=dict(width=width, height=900))
        def respond(route):
            request = route.request
            url = urlsplit(request.url)
            if url.path == '/agents/api/graph':
                if hold_graph:
                    held_graph.append(route); return
                route.fulfill(json=graph); return
            if url.path == '/agents/api/assistant':
                route.fulfill(json=dict(agent_id='butler')); return
            if url.path == '/agents/api/catalogue':
                route.fulfill(json=dict(services=[], classifications=[], skills=[])); return
            if url.path == '/agents/hud/data':
                hud_reads.append(1)
            if url.path == '/second-brain/hud/data' and hold_dashboard:
                held_dashboard.append(route); return
            if url.path == '/second-brain/hud/data' and failures:
                failures.pop()
                route.fulfill(status=503, json=dict(detail='Test dashboard unavailable')); return
            response = authenticated_client.request(request.method,
                url.path + ('?' + url.query if url.query else ''), content=request.post_data_buffer,
                headers={k:v for k,v in request.headers.items() if k.lower() in {'content-type','x-csrf-token'}})
            route.fulfill(status=response.status_code, body=response.content,
                headers={k:v for k,v in response.headers.items() if k.lower() not in {'content-length','content-encoding'}})
        context.route('https://brain.test/**', respond)
        page = context.new_page()
        errors = []
        page.on('pageerror', lambda e: errors.append(str(e)))
        page.goto('https://brain.test/agents?agent=butler')
        splash = page.locator('#brain-page-loading')
        playwright.expect(splash).to_be_visible()
        playwright.expect(splash.get_by_role('progressbar')).to_be_visible()
        assert page.locator('#agent-fleet').evaluate('(el) => el.inert')
        page.screenshot(path=str(tmp_path / f'brain-splash-{width}.png'))
        hold_graph.clear()
        for request in held_graph:
            request.fulfill(json=graph)
        playwright.expect(splash).to_be_hidden()
        link = page.get_by_role('link', name='Show second brain dashboard')
        assert page.locator('.fleet-toolbar > :first-child').get_attribute('aria-label') == 'Show second brain dashboard'
        assert page.locator('.fleet-hud-heading a').count() == 0
        playwright.expect(link).to_be_visible()
        playwright.expect(page.locator('.fleet-spaces .activity-view-name')).to_have_text('All activity')
        other = context.new_page()
        other.goto('https://brain.test/second-brain')
        with page.expect_response(lambda response: '/agents/hud/data' in response.url):
            other.evaluate("""async ({id, csrf}) => {
                const data = await fetch('/hfl-corpus/workspace-views').then(r=>r.json());
                await fetch('/hfl-corpus/view-preferences', {method:'PUT', headers:{'Content-Type':'application/json','X-CSRF-Token':csrf},
                    body:JSON.stringify({...data.preferences,manual:[id],dynamic:false})});
                localStorage.setItem('corpus:workspace-change',String(Date.now()));
            }""", dict(id=view['id'], csrf=headers()['X-CSRF-Token']))
        playwright.expect(page.locator('.fleet-spaces .activity-view-name')).to_have_text('Work')
        assert len(hud_reads) >= 2
        other.close()
        failures[:] = [True]
        hold_dashboard.append(True)
        link.click()
        playwright.expect(splash).to_be_visible()
        playwright.expect(splash.get_by_role('progressbar')).to_be_visible()
        page.screenshot(path=str(tmp_path / f'brain-dashboard-splash-{width}.png'))
        hold_dashboard.clear()
        for request in held_dashboard:
            respond(request)
        playwright.expect(page.get_by_role('button', name='Retry loading dashboard')).to_be_visible()
        page.get_by_role('button', name='Retry loading dashboard').click()
        playwright.expect(page.locator('#hud-loading')).to_be_hidden()
        playwright.expect(splash).to_be_hidden()
        playwright.expect(page.locator('#hud-active-spaces')).to_have_text('Work')
        workspace_return = page.get_by_role('link', name='Back to Second Brain workspace')
        assert workspace_return.get_attribute('href') == '/agents?agent=butler'
        assert workspace_return.get_attribute('title') == 'Back to Second Brain workspace'
        assert page.get_by_role('navigation', name='Breadcrumb').count() == 0
        assert page.locator('nav[aria-label="Distill views"] a[href="/agents"]').first.get_attribute('aria-current') == 'page'
        assert page.locator('nav[aria-label="Build tools"] a[href="/agents"]').count() == 0
        assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
        page.screenshot(path=str(tmp_path / f'brain-dashboard-{width}.png'), full_page=True)
        workspace_return.click()
        playwright.expect(link).to_be_visible()
        playwright.expect(page.locator('.fleet-spaces .activity-view-name')).to_have_text('Work')
        page.screenshot(path=str(tmp_path / f'brain-workspace-{width}.png'), full_page=True)
        assert not errors, errors
        browser.close()
