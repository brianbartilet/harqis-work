"""Retired Topics cannot return; provisional evidence remains available for matching."""
import json
import sqlite3
from uuid import uuid4

import pytest

from modules.hfl_corpus import entities
from workflows.hfl.entity_store import get_store
from workflows.hfl import entity_types, entity_retirement


@pytest.fixture
def corpus(monkeypatch):
    rows = [dict(id='one', text='Debug test in Python', title='Work', source='notes',
                 date='2026-10-28', tags=[], path='day.md', anchor='one', ref='https://example.test/corpus', entities={})]
    monkeypatch.setattr(entities, 'current_entries', lambda *a: rows)
    return rows


def legacy(store, row, mentions):
    # Simulate a pre-retirement database, bypassing the new write guard.
    with store.connection() as db:
        db.execute('INSERT INTO enrichment(id,hash,version,mentions) VALUES (?,?,?,?)',
                   (row['id'], entities.entry_hash(row), entities.VERSION, json.dumps(mentions)))


def test_singleton_is_provisional_but_repeated_and_curated_are_visible(corpus, authenticated_client):
    store = get_store()
    tool = entities.mention(corpus[0], 'tools', 'Python', 'Python', 'model-extracted')
    store.save('one', entities.entry_hash(corpus[0]), [tool])
    assert entities.entity_index()[0]['provisional']
    assert authenticated_client.get('/api/hfl/entities?include_provisional=false').json()['total'] == 0
    assert authenticated_client.get('/api/hfl/entities').json()['total'] == 1
    corpus.append({**corpus[0], 'id': 'two'})
    store.save('two', entities.entry_hash(corpus[1]), [tool])
    assert not entities.entity_index()[0]['provisional']
    corpus.pop()
    store.save_profile(tool['id'], 'tools', dict(name='Python'))
    assert not entities.entity_index()[0]['provisional']


def test_topics_are_rejected_at_extraction_storage_and_vocabulary(corpus, monkeypatch):
    from types import SimpleNamespace
    from apps.antropic.references.web.base_api_service import BaseApiServiceAnthropic
    import apps.antropic.config as config
    captured = {}
    def send(self, **kw):
        captured.update(kw)
        payload = dict(entries=[dict(id='one', mentions=[
            dict(kind='topics', name='Debug test in Python', evidence='Debug test in Python'),
            dict(kind='tools', name='Python', evidence='Debug test in Python')])])
        return SimpleNamespace(content=[SimpleNamespace(type='text', text=json.dumps(payload))], stop_reason='end_turn')
    monkeypatch.setattr(config, 'get_config', lambda name: {})
    monkeypatch.setattr(BaseApiServiceAnthropic, '__init__', lambda *a: None)
    monkeypatch.setattr(BaseApiServiceAnthropic, 'send_messages', send)
    assert [m['label'] for m in entities.extract_batch(corpus)['one']] == ['Python']
    assert 'extract only Python as tools' in captured['system']
    assert 'topics' not in {t['id'] for t in entity_types.listing()}
    with pytest.raises(ValueError):
        entity_types.create('Topics', '#ffffff', 'Keywords')
    get_store().save('one', 'hash', [dict(id='old', kind='topics')])
    assert get_store().records()['one']['mentions'] == []


def test_removal_preserves_activities_other_entities_backup_and_receipt(corpus):
    store = get_store()
    topic = entities.mention(corpus[0], 'topics', 'Debug test in Python', 'Python', 'model-extracted')
    tool = entities.mention(corpus[0], 'tools', 'Python', 'Python', 'model-extracted')
    legacy(store, corpus[0], [topic, tool])
    with store.connection() as db:
        db.execute('INSERT INTO profiles(id,kind,data) VALUES (?,?,?)',
                   (topic['id'], 'topics', json.dumps(dict(name=topic['label']))))
        db.execute('INSERT INTO entity_activity_links VALUES (?,?,?,?)', (topic['id'], 'one', 'owner', 'now'))
    before = json.dumps(corpus)
    preview = entity_retirement.preview()
    request = str(uuid4())
    result = entity_retirement.remove_topics(request, preview['selection_hash'], 'test')
    assert result['entities'] == 1 and result['mentions'] == 1
    assert json.dumps(corpus) == before
    assert store.records()['one']['mentions'] == [tool]
    assert topic['id'] not in store.profiles()
    assert entity_retirement.remove_topics(request, preview['selection_hash'], 'test') == result
    with sqlite3.connect(result['backup']) as db:
        assert len(json.loads(db.execute('SELECT mentions FROM enrichment').fetchone()[0])) == 2
    with store.connection() as db:
        assert db.execute('SELECT count(*) FROM entity_activity_links').fetchone()[0] == 0
        assert db.execute("SELECT count(*) FROM entity_audit WHERE action='type-retired'").fetchone()[0] == 1


def test_retirement_preserves_explicit_reclassification_and_rejects_stale_preview(corpus):
    store = get_store()
    topic = entities.mention(corpus[0], 'topics', 'Python', 'Python', 'model-extracted')
    legacy(store, corpus[0], [topic])
    preview = entity_retirement.preview()
    store.save_profile(topic['id'], 'tools', dict(name='Python'))
    with pytest.raises(ValueError, match='changed'):
        entity_retirement.remove_topics(str(uuid4()), preview['selection_hash'], 'test')
    fresh = entity_retirement.preview()
    result = entity_retirement.remove_topics(str(uuid4()), fresh['selection_hash'], 'test')
    assert result['mentions'] == 0
    assert store.records()['one']['mentions'][0]['kind'] == 'tools'
    assert store.profiles()[topic['id']]['kind'] == 'tools'


def test_legacy_topics_hidden_before_cleanup(corpus):
    topic = entities.mention(corpus[0], 'topics', 'Debug test in Python', 'Python', 'model-extracted')
    legacy(get_store(), corpus[0], [topic])
    assert entities.entity_index() == []
    assert not any(n['kind'] == 'topics' for n in entities.graph()['nodes'])


def test_removal_rolls_back_when_audit_cannot_be_saved(corpus, monkeypatch):
    from workflows.hfl import entity_merges
    store = get_store()
    topic = entities.mention(corpus[0], 'topics', 'Python testing', 'Python', 'model-extracted')
    legacy(store, corpus[0], [topic])
    def fail(*args, **kwargs):
        raise RuntimeError('audit unavailable')
    monkeypatch.setattr(entity_merges, 'record_event', fail)
    with pytest.raises(RuntimeError, match='audit unavailable'):
        entity_retirement.remove_topics(str(uuid4()), entity_retirement.preview()['selection_hash'], 'test')
    assert store.records()['one']['mentions'] == [topic]
    with store.connection() as db:
        assert db.execute('SELECT count(*) FROM entity_operations').fetchone()[0] == 0


def test_retirement_endpoint_requires_owner(corpus, authenticated_client):
    from fastapi.testclient import TestClient
    from main import app
    with TestClient(app) as client:
        assert client.get('/api/hfl/entities/types/topics/removal-preview').status_code == 401
        assert client.post('/api/hfl/entities/types/topics/remove', json={
            'request_id': str(uuid4()), 'selection_hash': '0' * 64}).status_code == 401
    preview = authenticated_client.get('/api/hfl/entities/types/topics/removal-preview').json()
    result = authenticated_client.post('/api/hfl/entities/types/topics/remove', json={
        'request_id': str(uuid4()), 'selection_hash': preview['selection_hash']})
    assert result.status_code == 200


def test_retirement_retires_work_without_erasing_completed_audits(corpus):
    from workflows.hfl.entity_run_storage import read_run
    store = get_store()
    topic = entities.mention(corpus[0], 'topics', 'Python testing', 'Python', 'model-extracted')
    legacy(store, corpus[0], [topic])
    pair = dict(id='pair', ids=[topic['id'], 'other'], kind='topics', state='deferred', left={}, right={})
    store.state('consolidation:active', dict(id='active', state='running', pairs={'pair': pair}))
    store.state('consolidation:report', dict(id='report', state='complete', pairs={'pair': pair}))
    with store.connection() as db:
        db.execute('INSERT INTO entity_resolutions VALUES (?,?,?,?)',
                   ('one', 'old-mention', topic['id'], json.dumps(dict(active=True))))
        db.execute('INSERT INTO entity_resolution_outcomes VALUES (?,?,?,?,?,?)',
                   ('one', 'old-mention', 'resolved', 'v', '{}', 1))
    entity_retirement.remove_topics(str(uuid4()), entity_retirement.preview()['selection_hash'], 'test')
    with store.connection() as db:
        assert read_run(db, 'active')['pairs']['pair']['state'] == 'stale'
        assert read_run(db, 'report')['pairs']['pair']['state'] == 'deferred'
        assert db.execute('SELECT count(*) FROM entity_resolutions').fetchone()[0] == 0
        assert db.execute('SELECT count(*) FROM entity_resolution_outcomes').fetchone()[0] == 0


@pytest.mark.parametrize('width', [1100, 390])
def test_provisional_filter_browser(corpus, authenticated_client, tmp_path, width):
    from pathlib import Path
    pw = pytest.importorskip('playwright.sync_api')
    store = get_store()
    tool = entities.mention(corpus[0], 'tools', 'Python', 'Python', 'model-extracted')
    store.save('one', entities.entry_hash(corpus[0]), [tool])
    with pw.sync_playwright() as engine:
        options = {'headless': True}
        if not Path(engine.chromium.executable_path).exists():
            options['channel'] = 'msedge'
        browser = engine.chromium.launch(**options)
        try:
            page = browser.new_page(viewport={'width': width, 'height': 1000})
            errors = []
            page.on('pageerror', lambda e: errors.append(str(e)))
            def route_request(route):
                req = route.request
                response = authenticated_client.request(req.method, req.url.replace('https://entities.test', ''),
                    content=req.post_data, headers={'content-type': 'application/json'})
                route.fulfill(status=response.status_code, body=response.content,
                    headers={k:v for k,v in response.headers.items() if k.lower() not in {'content-encoding', 'content-length'}})
            page.route('https://entities.test/**', route_request)
            page.goto('https://entities.test/hfl-corpus/entities')
            page.wait_for_selector('#entity-results:not([hidden])')
            assert page.locator('.entity-card').count() == 0
            page.select_option('#filter-maturity', 'all')
            assert page.locator('.entity-card').count() == 1
            page.fill('#entity-query', 'Python')
            assert page.locator('.entity-card').count() == 1
            page.click('#clear-filters')
            assert page.locator('.entity-card').count() == 0
            assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
            page.screenshot(path=str(tmp_path / f'entity-signal-{width}.png'), full_page=True)
            assert not errors
        finally:
            browser.close()
