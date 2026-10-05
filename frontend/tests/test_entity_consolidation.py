"""Exercise agent decisions against the real isolated entity store and API."""
from uuid import uuid4

import pytest

from modules.hfl_corpus import entities
from workflows.hfl import entity_consolidation as consolidation, entity_merges, entity_matching
from workflows.hfl.entity_store import get_store
from workflows.hfl.entity_candidates import candidates, preferred

FACT = 'Kevin led the Mercury migration with Priya in Singapore during March 2025.'


@pytest.fixture
def corpus(monkeypatch):
    monkeypatch.setattr(entity_matching, 'dispatch_pending', lambda: None)
    monkeypatch.setattr(entity_merges, 'flush_audits', lambda: None)
    rows = [dict(id=f'entry-{i}', title='Migration meeting', text=FACT, source='notes',
                 date='2026-09-01', tags=[], path='day.md', anchor=str(i), ref='') for i in range(2)]
    monkeypatch.setattr(entities, 'current_entries', lambda: rows.copy())
    for row, name in zip(rows, ['Kevin Hildgendarff', 'Kevin Hildgendorff']):
        mention = entities.mention(row, 'people', name, FACT, 'model-extracted')
        get_store().save(row['id'], entities.entry_hash(row), [mention])
    return rows


def decision(**changes):
    return dict(decision='merge', reason='Same specific project and coworkers; OCR surname variant.',
                contradictions=[], facts=[dict(left_quote=FACT, right_quote=FACT, explanation='Mercury migration with Priya in Singapore in March 2025')],
                aliases=[], partial_aliases=[], **changes)


def first():
    run = consolidation.begin()
    return run, run['pairs'][0]


def test_agent_merge_retains_undo_but_suppresses_individual_hfl(corpus):
    run, pair = first()
    value = decision()
    value['aliases'] = ['Kevin H.']
    result = consolidation.decide(run['id'], pair['id'], value)
    assert result['state'] == 'merged'
    assert consolidation.decide(run['id'], pair['id'], value)['operation'] == result['operation']
    merged = entities.entity_index()[0]
    assert len(merged['entries']) == 2
    assert 'Kevin H.' in merged['profile']['aliases']
    assert merged['profile']['alias_sources']['Kevin H.'] == 'llm'
    event = entity_merges.history(merged['id'])[0]
    assert event['delivery'] == 'not-required'
    assert event['data']['automatic']['run_id'] == run['id']
    consolidation.finish(run['id'])
    assert 'people' in consolidation.report(consolidation.load(run['id']))
    entity_merges.unmerge(merged['id'], str(uuid4()), 'undo', 'owner')
    assert len(entities.entity_index()) == 2
    with get_store().connection() as db:
        assert entity_matching.blocked(db, pair['ids'])


def test_manual_merge_still_delivers_individual_audit(corpus):
    from modules.hfl_corpus.entity_merge_api import MergePreview, build_preview
    preview = build_preview(MergePreview(entity_ids=[e['id'] for e in entities.entity_index()], name='Kevin Hildgendorff'))
    result = entity_merges.commit_merge(preview, str(uuid4()), 'manual', 'owner')
    assert entity_merges.history(result['entity_id'])[0]['delivery'] == 'pending'


def test_stale_evidence_and_invented_quotes_do_not_merge(corpus):
    run, pair = first()
    invalid = decision()
    invalid['facts'][0]['left_quote'] = 'A completely invented activity excerpt cannot justify this identity merge.'
    assert consolidation.decide(run['id'], pair['id'], invalid)['state'] == 'deferred'
    assert len(entities.entity_index()) == 2
    with pytest.raises(ValueError, match='already recorded'):
        consolidation.decide(run['id'], pair['id'], decision())


def test_stale_profile_is_rechecked(corpus):
    run, pair = first()
    get_store().save_profile(pair['ids'][0], 'people', {'name': 'Different person', 'notes': 'Changed'})
    assert consolidation.decide(run['id'], pair['id'], decision())['state'] == 'stale'
    assert len(entities.entity_index()) == 2


def test_explicit_conflict_and_alias_only_are_not_evidence(corpus):
    _, pair = first()
    pair['left']['external_id'], pair['right']['external_id'] = 'one', 'two'
    assert not consolidation.corroborated(decision(), pair)
    pair['left']['external_id'] = pair['right']['external_id'] = None
    pair['left']['activity'] = []
    assert not consolidation.corroborated(decision(), pair)


def test_partial_hints_discover_same_type_candidates_without_approval():
    a = dict(id='a', kind='pets', label='Mittens', entries=[], profile={'partial_aliases': ['fluffy']})
    b = dict(id='b', kind='pets', label='The fluffy cat', entries=[], profile={})
    c = dict(id='c', kind='people', label='The fluffy cat', entries=[], profile={})
    assert candidates([a, b, c]) == [('a', 'b')]


def test_unique_related_items_rank_below_curated_preference(corpus):
    a, b = entities.entity_index()
    b['entries'] = [dict(id='x'), dict(id='x'), dict(id='y')]
    assert preferred([a, b])['id'] == b['id']
    a['profile'] = {'name': a['label'], 'preferred_name': True}
    assert preferred([a, b])['id'] == a['id']


def test_api_alias_edit_and_pending_finish(corpus, authenticated_client):
    identity = entities.entity_index()[0]['id']
    response = authenticated_client.post('/api/hfl/entities/profile/'+identity,
        json={'name': 'Kevin Hildgendorff', 'aliases': [' Kevin H. ', 'Kevin H.'], 'partial_aliases': ['Hildg'], 'preferred_name': True})
    assert response.status_code == 200
    assert response.json()['profile']['aliases'] == ['Kevin H.']
    assert response.json()['profile']['alias_sources']['Hildg'] == 'user'
    assert authenticated_client.get('/api/hfl/entities?q=Hildg').json()['total'] == 2
    run = authenticated_client.post('/api/hfl/entities/consolidation/begin').json()
    assert authenticated_client.post('/api/hfl/entities/consolidation/'+run['id']+'/finish').status_code == 409
    assert consolidation.begin()['id'] == run['id']


def test_hermes_owner_stops_legacy_matching(corpus):
    run, _ = first()
    assert entity_matching.process_batch('legacy-job')['owner'] == 'hermes'
    assert len(entities.entity_index()) == 2
    assert entity_matching.request_scan()['owner'] == 'hermes'
    get_store().save('new', 'hash', [{'id': 'new-mention'}], match=True)
    with get_store().connection() as db:
        assert db.execute('SELECT count(*) FROM entity_match_jobs').fetchone()[0] == 0


def test_unchanged_entities_are_not_revisited_and_changed_ones_are(corpus, monkeypatch):
    run, pair = first()
    d = decision(); d['decision'] = 'review'
    consolidation.decide(run['id'], pair['id'], d)
    consolidation.finish(run['id'])
    from datetime import datetime, timedelta
    class Tomorrow(datetime):
        @classmethod
        def now(cls, tz=None):
            return datetime.now(tz) + timedelta(days=1)
    monkeypatch.setattr(consolidation, 'datetime', Tomorrow)
    second = consolidation.begin()
    assert second['pending_total'] == 0
    consolidation.finish(second['id'])
    # Re-finishing an older run must not replace the newer checkpoint.
    get_store().state('consolidation-checkpoint', {'sentinel': 'newer'})
    consolidation.finish(run['id'])
    assert get_store().state('consolidation-checkpoint') == {'sentinel': 'newer'}


def test_commit_receipt_recovers_crash_before_pair_checkpoint(corpus, monkeypatch):
    run, pair = first()
    original = consolidation.save
    monkeypatch.setattr(consolidation, 'save', lambda run: (_ for _ in ()).throw(RuntimeError('crash')))
    with pytest.raises(RuntimeError, match='crash'):
        consolidation.decide(run['id'], pair['id'], decision())
    assert len(entities.entity_index()) == 1
    monkeypatch.setattr(consolidation, 'save', original)
    result = consolidation.decide(run['id'], pair['id'], decision())
    assert result['state'] == 'merged' and result['related_items'] == 2
    assert result['result_name']


def test_concurrent_replays_serialize_to_one_operation(corpus):
    from concurrent.futures import ThreadPoolExecutor
    run, pair = first()
    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(consolidation.decide, run['id'], pair['id'], decision()) for _ in range(2)]
        receipts = [future.result()['operation'] for future in futures]
    assert receipts[0] == receipts[1]
    assert len(entities.entity_index()) == 1


def test_failed_report_dispatch_keeps_intent_and_recovery_queues_once(corpus, monkeypatch):
    from types import SimpleNamespace
    from workflows.hfl.tasks.entity_consolidation import deliver_entity_consolidation
    run, pair = first()
    d = decision(); d['decision'] = 'review'
    consolidation.decide(run['id'], pair['id'], d)
    consolidation.finish(run['id'])
    monkeypatch.setattr(deliver_entity_consolidation, 'apply_async', lambda **kwargs: (_ for _ in ()).throw(ConnectionError()))
    with pytest.raises(ConnectionError):
        consolidation.dispatch_reports()
    assert consolidation.load(run['id'])['state'] == 'complete'
    sent = []
    monkeypatch.setattr(deliver_entity_consolidation, 'apply_async', lambda **kwargs: sent.append(kwargs) or SimpleNamespace(id='task-1'))
    assert consolidation.dispatch_reports() == ['task-1']
    assert consolidation.dispatch_reports() == []
    assert len(sent) == 1


def test_conflicting_curated_profiles_remain_separate(corpus):
    for entity in entities.entity_index():
        get_store().save_profile(entity['id'], entity['kind'], {'name': entity['label'], 'notes': 'Owner curated profile'})
    run, pair = first()
    result = consolidation.decide(run['id'], pair['id'], decision())
    assert result['state'] == 'deferred' and 'curated' in result['note']


def test_automated_reports_do_not_supply_matching_evidence(corpus):
    corpus[0]['source'] = 'entity-consolidation'
    rows = consolidation.current_entities()
    assert all(e['source'] != 'entity-consolidation' for row in rows for e in row['entries'])


def test_delivery_is_idempotent_and_does_not_remerge(corpus, monkeypatch):
    from workflows.hfl.tasks import entity_consolidation as delivery
    from workflows.hfl import persistence
    from workflows.hfl.tasks import activity_radar
    run, pair = first()
    consolidation.decide(run['id'], pair['id'], decision())
    consolidation.finish(run['id'])
    sent, saved = [], []
    def submit(entry, **kwargs):
        saved.append(kwargs)
        return {'delivery': 'persisted', 'path': '2026-10-04.md'}
    monkeypatch.setattr(persistence, 'submit_hfl_entry', submit)
    monkeypatch.setattr(activity_radar, 'corpus_document_url', lambda *a, **k: 'https://example.test/report')
    monkeypatch.setattr(activity_radar, '_notify', lambda text: sent.append(text) or [123])
    delivery.deliver(run['id'])
    delivery.deliver(run['id'])
    assert len(sent) == len(saved) == 1
    assert len(entities.entity_index()) == 1


def test_delivery_uncertainty_does_not_duplicate_telegram(corpus, monkeypatch):
    from workflows.hfl.tasks import entity_consolidation as delivery
    from workflows.hfl.tasks import activity_radar
    run, pair = first()
    d = decision(); d['decision'] = 'review'
    consolidation.decide(run['id'], pair['id'], d)
    consolidation.finish(run['id'])
    stored = consolidation.load(run['id'])
    stored['delivery'] = {'hfl': {'delivery': 'persisted'}, 'url': 'https://example.test', 'telegram_state': 'sending'}
    consolidation.save(stored)
    monkeypatch.setattr(activity_radar, '_notify', lambda text: pytest.fail('Must not resend uncertain delivery'))
    with pytest.raises(ValueError, match='uncertain'):
        delivery.deliver(run['id'])


def test_alias_editor_saves_partial_hints_and_preference(corpus, authenticated_client, tmp_path):
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
            card = page.locator('#entity-list > details').first
            card.locator(':scope > summary').click()
            card.locator('.profile-editor > summary').click()
            card.locator('[name=aliases]').fill('Kevin H.\nKevin Hildgendorff')
            card.locator('[name=partial_aliases]').fill('Hildgend')
            card.get_by_label('Prefer this display name during automatic merges').check()
            card.get_by_role('button', name='Save profile').click()
            playwright.expect(page.locator('#entity-status')).to_contain_text('Profile saved.')
            stored = next(p for p in get_store().profiles().values() if p.get('aliases'))
            assert stored['aliases'] == ['Kevin H.', 'Kevin Hildgendorff']
            assert stored['partial_aliases'] == ['Hildgend'] and stored['preferred_name']
            page.set_viewport_size({'width': 390, 'height': 844})
            assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
            page.screenshot(path=str(tmp_path / 'aliases-mobile.png'), full_page=True)
            assert not errors
        finally:
            browser.close()
