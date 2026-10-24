import pytest
from fastapi.testclient import TestClient
from modules.hfl_shares.security import make_csrf_token
from modules.second_brain import hud

read_projections = hud.projections


@pytest.fixture(autouse=True)
def isolated_hud(monkeypatch):
    from modules.hfl_corpus.graph_views import connection
    from modules.hfl_corpus import workspace_views
    with connection() as db:
        hud.schema(db)
        workspace_views.schema(db)
        db.execute('DELETE FROM second_brain_hud_layout')
        db.execute('DELETE FROM corpus_view_preferences')
        db.execute('DELETE FROM corpus_workspace_views')
        db.execute('DELETE FROM corpus_view_schedules')
    monkeypatch.setattr(hud, 'projections', lambda: ({}, ''))


def headers():
    return {'X-CSRF-Token': make_csrf_token('frontend-test-user')}


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
    assert '/static/js/second-brain-hud.js?v=' in page.text
    assert '/static/css/second-brain-hud.css?v=' in page.text
    assert 'Build with agent' in page.text
    catalog = hud.inventory()
    assert len([item for item in catalog if item['source_task']]) == 18
    assert next(item for item in catalog if item['operation_id'] == 'hud.hud_calendar.show_calendar_information')['schedules']


def test_layout_roundtrip_and_stale_revision(authenticated_client):
    client = authenticated_client
    original = client.get('/second-brain/hud/data').json()['layout']
    original['widgets'][0].update(size='1x4', animation='typing', hidden=True)
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
