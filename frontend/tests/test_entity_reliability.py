"""Reliability contracts against isolated stores and the real authenticated API."""
import json
from copy import deepcopy
import time
from uuid import uuid4

import pytest

from modules.hfl_corpus import entities
from workflows.hfl import entity_executions as executions, entity_integrity as integrity
from workflows.hfl import entity_resolution as resolution, entity_consolidation as runs, entity_matching as matching
from workflows.hfl.entity_store import get_store
from test_entity_soul import soul_data, save  # noqa: F401
from test_entity_consolidation import corpus, alias_group, decision  # noqa: F401


def test_quarantine_withholds_existing_assignment_and_restores_after_review(soul_data, authenticated_client):
    save(authenticated_client)
    resolution.process_pending(use_model=False)
    assert entities.projection()[0]['mentions'][0]['id'] == 'brian'
    integrity.set_review('brian', True, 'Contradictory source context', [], 'owner')
    assert entities.projection()[0]['mentions'][0]['id'] == soul_data[1]['id']
    resolution.process_pending(use_model=False)
    with get_store().connection() as db:
        assert db.execute('SELECT outcome FROM entity_resolution_outcomes').fetchone()[0] == 'integrity-review'
    integrity.set_review('brian', False, 'Reviewed original evidence', [], 'owner')
    assert entities.projection()[0]['mentions'][0]['id'] == 'brian'


def test_quarantine_during_evaluation_prevents_assignment(soul_data, monkeypatch):
    def evaluate(pairs, **kwargs):
        integrity.set_review('brian', True, 'Conflicting identities discovered', [], 'owner')
        return [dict(id=p['id'], decision='separate') for p in pairs], 'test'
    monkeypatch.setattr(matching, 'evaluate', evaluate)
    with pytest.raises(ValueError, match='state changed'):
        resolution.process_batch()
    with get_store().connection() as db:
        assert db.execute('SELECT count(*) FROM entity_resolutions').fetchone()[0] == 0


def test_quarantine_blocks_alias_projection_for_new_mentions(corpus):
    run = runs.begin()
    pair = run['pairs'][0]
    merged = runs.decide(run['id'], pair['id'], decision())['operation']['entity_id']
    integrity.set_review(merged, True, 'Mixed identities suspected', [], 'owner')
    projected = entities.projection()
    assert all(m['id'] != merged and m['resolution'] == 'integrity-review'
               for row in projected for m in row['mentions'])
    assert all(m['id'].startswith('integrity-mention-') for row in projected for m in row['mentions'])
    from modules.hfl_corpus.entities_api import creation_suggestions, TypedProfile
    suggestions = creation_suggestions(TypedProfile(kind='people', name=pair['left']['name']))
    assert all(not s['id'].startswith('integrity-mention-') for s in suggestions)
    with get_store().connection() as db:
        assert matching.blocked(db, [projected[0]['mentions'][0]['id'], 'another-target'])
        db.execute('INSERT INTO entity_activity_links VALUES (?,?,?,?)',
                   (merged, corpus[0]['id'], 'owner', '2026-10-20T00:00:00Z'))
    assert any(m['id'] == merged and m['method'] == 'user-confirmed'
               for row in entities.projection() for m in row['mentions'])
    # Clearing review restores the existing reversible grouping, without a new merge.
    integrity.set_review(merged, False, 'Original sources reviewed', [], 'owner')
    assert all(m['id'] == merged for row in entities.projection() for m in row['mentions'])


def test_failed_entry_does_not_starve_next_job_and_attempts_are_durable(soul_data, monkeypatch):
    store = get_store()
    store.save('later', 'revision', [], match=True)
    original = resolution.process_batch
    def process(use_model=True, entry_id=None):
        if entry_id == 'entry-one':
            raise RuntimeError('Private provider details')
        return original(use_model=False, entry_id=entry_id)
    monkeypatch.setattr(resolution, 'process_batch', process)
    result = resolution.process_pending()
    assert result['processed'] == 1
    for _ in range(4):
        with store.connection() as db:
            db.execute('UPDATE entity_resolution_jobs SET next_attempt=0')
        resolution.process_pending()
    health = resolution.status()
    assert health['failed'] == 1 and health['pending'] == 0
    assert health['failures'][0]['attempts'] == 5
    assert 'Private provider' not in json.dumps(health)
    assert resolution.retry_failed('entry-one') == {'requeued': 1}
    assert resolution.status()['pending'] == 1


def test_legacy_queue_migration_and_backoff_task_continuation(monkeypatch, tmp_path):
    import sqlite3
    from workflows.knowledge.tasks.connected_hfl import resolve_corpus_entities
    path = tmp_path / 'legacy.sqlite3'
    with sqlite3.connect(path) as db:
        db.execute('CREATE TABLE entity_resolution_jobs(entry_id TEXT PRIMARY KEY, revision TEXT NOT NULL, queued_at REAL NOT NULL DEFAULT 0)')
        db.execute("INSERT INTO entity_resolution_jobs VALUES ('entry','hash',123)")
    monkeypatch.setenv('HARQIS_ENTITIES_DB', str(path))
    store = get_store()
    with store.connection() as db:
        row = db.execute('SELECT * FROM entity_resolution_jobs').fetchone()
        assert row['created_at'] > 0 and row['queued_at'] == 123 and row['attempts'] == 0
    calls = []
    monkeypatch.setattr(resolution, 'process_pending', lambda: dict(pending=0, processed=0, retry_after=60))
    monkeypatch.setattr(resolve_corpus_entities, 'apply_async', lambda **kwargs: calls.append(kwargs))
    resolve_corpus_entities.run()
    assert calls[0]['countdown'] == 60


def test_unresolved_work_reopens_when_target_changes(soul_data):
    resolution.process_batch(use_model=False)
    assert resolution.status()['outcomes']['no-candidate'] == 1
    assert resolution.process_batch(use_model=False)['processed'] == 0
    store = get_store()
    store.save_profile('brian', 'people', dict(name='Brian Bartilet', aliases=['Brian'], notes='New corroboration'))
    assert resolution.status()['pending'] == 1


def test_unchanged_source_and_unrelated_profile_do_not_requeue_ambiguity(soul_data):
    rows, mention = soul_data
    resolution.process_batch(use_model=False)
    store = get_store()
    store.save(rows[0]['id'], entities.entry_hash(rows[0]), [mention], match=True)
    store.save_profile('unrelated', 'people', dict(name='Alexandra Unrelated', aliases=[], notes='Different person'))
    assert resolution.status()['pending'] == 0


def test_quarantine_blocks_automatic_merge_at_commit(corpus):
    from modules.hfl_corpus.entity_merge_api import MergePreview, build_preview
    from workflows.hfl import entity_merges
    rows = entities.entity_index()
    store = get_store()
    store.save_profile(rows[0]['id'], rows[0]['kind'], dict(name=rows[0]['label']))
    preview = build_preview(MergePreview(entity_ids=[r['id'] for r in rows], name=rows[0]['label'], evidence='Review'))
    preview['automatic'] = {'run_id': 'test'}
    integrity.set_review(rows[0]['id'], True, 'Contradictory evidence', [], 'owner')
    with pytest.raises(ValueError, match='changed'):
        entity_merges.commit_merge(preview, str(uuid4()), 'fingerprint', 'entity-matcher:hermes')
    # Quarantine adds an isolated projection; persisted merges are the safety invariant.
    with store.connection() as db:
        assert db.execute('SELECT count(*) FROM entity_merges').fetchone()[0] == 0


def test_api_execution_close_recovery(alias_group, authenticated_client, monkeypatch):
    run, _ = alias_group
    monkeypatch.setattr(runs, 'dispatch_reports', lambda *args: [])
    url = '/api/hfl/entities/consolidation/' + run['id']
    start = authenticated_client.post(url + '/executions', json={'execution_id': 'api-window', 'max_pairs': 1})
    assert start.status_code == 200
    payload = {'reason': 'budget'}
    close = authenticated_client.post(url + '/executions/api-window/close', json=payload)
    assert close.status_code == 200
    assert authenticated_client.post(url + '/executions/api-window/close', json=payload).json() == close.json()
    report = authenticated_client.get('/api/hfl/entities/consolidation/' + close.json()['report_id'])
    assert report.json()['execution_report']['remaining_selected'] == 1


def test_bounded_execution_reports_partial_work_once(alias_group):
    run, _ = alias_group
    execution = executions.start(run['id'], 'window-one', max_pairs=1)
    assert executions.start(run['id'], 'window-one', max_pairs=1) == execution
    selected = execution['pair_ids'][0]
    other = next(p for p in run['pairs'] if p['id'] != selected)
    with pytest.raises(ValueError, match='outside'):
        runs.decide(run['id'], other['id'], dict(decision='review', reason='Need context', contradictions=[], facts=[]))
    runs.decide(run['id'], selected, dict(decision='review', reason='Need original context', contradictions=[], facts=[]))
    result = executions.close(run['id'], 'window-one', 'exhausted')
    assert result['state'] == 'complete' and result['remaining_eligible'] > 0
    assert result['operation_ids'] == [] and result['verified']
    assert executions.close(run['id'], 'window-one', 'exhausted') == result
    report = runs.load(result['report_id'])
    assert len(report['pairs']) == 1 and 'Need original context' in runs.report(report)
    assert runs.load(run['id'])['state'] == 'running'
    executions.start(run['id'], 'window-two', max_pairs=1)


def test_execution_budget_and_merge_receipts(alias_group):
    run, payload = alias_group
    executions.start(run['id'], 'merge-window')
    merged = runs.merge_group(run['id'], payload)
    result = executions.close(run['id'], 'merge-window', 'exhausted')
    assert result['event_ids'] == [merged['operation']['event_id']]
    assert len(result['operation_ids']) == 1
    assert result['verified']
    assert runs.merged_group_count(runs.load(result['report_id'])['pairs'].values()) == 1


def test_close_recovers_commit_before_lost_run_save(alias_group):
    run, payload = alias_group
    executions.start(run['id'], 'lost-save')
    before = deepcopy(runs.load(run['id']))
    merged = runs.merge_group(run['id'], payload)
    runs.save(before)  # Simulate a crash after the atomic merge but before run persistence.
    result = executions.close(run['id'], 'lost-save', 'exhausted')
    assert result['event_ids'] == [merged['operation']['event_id']]
    assert result['verified'] and result['remaining_selected'] == 0


def test_execution_and_global_finish_notify_merge_only_once(alias_group, monkeypatch):
    from workflows.hfl.tasks import entity_consolidation as delivery, activity_radar
    from workflows.hfl import persistence
    run, payload = alias_group
    executions.start(run['id'], 'delivery')
    runs.merge_group(run['id'], payload)
    result = executions.close(run['id'], 'delivery', 'exhausted')
    sent, saved = [], []
    monkeypatch.setattr(persistence, 'submit_hfl_entry',
                        lambda entry, **kwargs: saved.append(kwargs['dedup_key']) or {'delivery': 'persisted'})
    monkeypatch.setattr(activity_radar, 'corpus_document_url', lambda *a, **k: 'https://example.test/report')
    monkeypatch.setattr(activity_radar, '_notify', lambda text: sent.append(text) or [123])
    assert delivery.deliver(result['report_id'])['telegram_state'] == 'sent'
    assert delivery.deliver(result['report_id'])['telegram_state'] == 'sent'
    runs.finish(run['id'])
    assert delivery.deliver(run['id'])['telegram_state'] == 'suppressed'
    assert len(sent) == 1 and len(set(saved)) == len(saved) == 2


def test_expired_execution_cannot_commit(corpus):
    run = runs.begin()
    executions.start(run['id'], 'expired')
    saved = runs.load(run['id'])
    saved['executions']['expired']['deadline'] = time.time() - 1
    runs.save(saved)
    with pytest.raises(ValueError, match='budget'):
        runs.decide(run['id'], run['pairs'][0]['id'], decision())
    assert executions.close(run['id'], 'expired', 'budget')['state'] == 'complete'


def test_separation_is_shared_with_resolver(corpus):
    run = runs.begin()
    pair = run['pairs'][0]
    runs.decide(run['id'], pair['id'], dict(decision='separate', reason='Different people', facts=[], contradictions=[]))
    with get_store().connection() as db:
        assert matching.blocked(db, pair['ids'])
        assert db.execute("SELECT count(*) FROM entity_audit WHERE action='kept-separate'").fetchone()[0] == 1
    assert integrity.reverse_separation(*pair['ids'], 'Reviewed new evidence', 'owner')['removed_blocks'] == 1
    with get_store().connection() as db:
        assert not matching.blocked(db, pair['ids'])
        matching.block_members(db, pair['ids'], 'consolidation-separate')
        matching.block_members(db, pair['ids'], 'unmerged')
    assert integrity.reverse_separation(*pair['ids'], 'Try again', 'owner')['removed_blocks'] == 0
    with get_store().connection() as db:
        assert matching.blocked(db, pair['ids'])


def test_manual_creation_requires_distinct_choice_and_directory_explains(soul_data, authenticated_client):
    payload = dict(kind='people', name='Brian Bartilet')
    response = authenticated_client.post('/api/hfl/entities/create', json=payload)
    assert response.status_code == 200
    assert response.json()['state'] == 'possible-existing'
    assert response.json()['suggestions'][0]['id'] == 'brian'
    integrity.set_review('brian', True, 'Two conflicting roles', [], 'owner')
    rows = authenticated_client.get('/api/hfl/entities').json()['entities']
    assert next(r for r in rows if r['id'] == 'brian')['identity_status'][0]['state'] == 'integrity-review'
    created = authenticated_client.post('/api/hfl/entities/create', json={**payload, 'confirm_distinct': True})
    assert created.status_code == 200 and created.json()['id'].startswith('manual-')


def test_creation_suggestions_browser(soul_data, authenticated_client, tmp_path):
    from pathlib import Path
    playwright = pytest.importorskip('playwright.sync_api')
    with playwright.sync_playwright() as engine:
        options = {'headless': True}
        if not Path(engine.chromium.executable_path).exists():
            options['channel'] = 'msedge'
        browser = engine.chromium.launch(**options)
        try:
            page = browser.new_page(viewport={'width': 1100, 'height': 1000})
            errors = []
            page.on('pageerror', lambda error: errors.append(str(error)))
            def route_request(route):
                req = route.request
                response = authenticated_client.request(req.method, req.url.replace('https://entities.test', ''),
                    content=req.post_data_buffer, headers={'content-type': req.headers.get('content-type', 'application/json')})
                route.fulfill(status=response.status_code, body=response.content,
                    headers={k:v for k,v in response.headers.items() if k.lower() not in {'content-encoding', 'content-length'}})
            page.route('https://entities.test/**', route_request)
            page.goto('https://entities.test/hfl-corpus/entities')
            playwright.expect(page.locator('#entity-list > details').first).to_be_visible()
            page.locator('#entity-type-manager > summary').click()
            form = page.locator('#entity-create-form')
            form.locator('[name=name]').fill('Brian Bartilet')
            form.locator('[name=kind]').select_option('people')
            form.get_by_role('button', name='Add entity', exact=True).click()
            panel = page.locator('#create-entity-suggestions')
            playwright.expect(panel.get_by_role('button', name='Create a distinct entity')).to_be_visible()
            panel.get_by_role('button', name='Brian Bartilet', exact=False).click()
            playwright.expect(page.locator('#type-feedback')).to_contain_text('No new entity created')
            form.locator('[name=name]').fill('Brian Different')
            panel.get_by_role('button', name='Create a distinct entity').click()
            playwright.expect(page.locator('#type-feedback')).to_contain_text('form changed')
            playwright.expect(panel).to_be_hidden()
            form.locator('[name=name]').fill('Brian Bartilet')
            form.get_by_role('button', name='Add entity', exact=True).click()
            playwright.expect(panel).to_be_visible()
            page.screenshot(path=str(tmp_path / 'entity-suggestions-desktop.png'), full_page=True)
            page.set_viewport_size({'width': 390, 'height': 844})
            assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
            page.screenshot(path=str(tmp_path / 'entity-suggestions-mobile.png'), full_page=True)
            panel.get_by_role('button', name='Create a distinct entity').click()
            playwright.expect(page.locator('#type-feedback')).to_contain_text('Distinct entity created')
            playwright.expect(panel).to_be_hidden()
            assert not errors
        finally:
            browser.close()
