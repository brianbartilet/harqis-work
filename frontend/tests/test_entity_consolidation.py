"""Exercise agent decisions against the real isolated entity store and API."""
import json
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


def test_pending_priority_is_global_type_then_occurrence_not_insertion():
    kinds = ['people', 'companies', 'tools', 'pets', 'apps', 'games', 'topics']
    pairs = {}
    for kind in reversed(kinds):
        for count in [1, 50]:
            key = f'{kind}-{count}'
            pairs[key] = dict(id=key, state='pending', kind=kind, ids=[key, key+'-alias'],
                left={'id': key, 'related_items': count},
                right={'id': key+'-alias', 'related_items': 0},
                signals={'exact': True, 'contact': False, 'partial': False, 'fuzzy': 1})
    run = dict(id='test', state='running', initial=True, delivery={}, pairs=pairs)
    expected = [f'{kind}-{count}' for kind in kinds for count in [50, 1]]
    assert [p['id'] for p in consolidation.view(run, limit=20)['pairs']] == expected
    assert [p['id'] for p in consolidation.view(run, offset=2, limit=2)['pairs']] == expected[2:4]


@pytest.fixture
def alias_group(corpus):
    row = dict(corpus[0], id='entry-2', anchor='2')
    corpus.append(row)
    mention = entities.mention(row, 'people', 'Kevin Hildgendorf', FACT, 'model-extracted')
    get_store().save(row['id'], entities.entry_hash(row), [mention])
    run = consolidation.begin()
    anchor = run['pairs'][0]['ids'][0]
    decisions = {p['id']: decision() for p in run['pairs'] if anchor in p['ids']}
    assert len(decisions) == 2
    return run, dict(anchor_id=anchor, decisions=decisions, contradictions=[])


def test_alias_group_commits_once_and_undo_restores_all(alias_group, authenticated_client):
    run, payload = alias_group
    url = '/api/hfl/entities/consolidation/' + run['id'] + '/groups'
    response = authenticated_client.post(url, json=payload)
    assert response.status_code == 200, response.text
    result = response.json()
    assert result['state'] == 'merged' and len(result['pair_ids']) == 2
    assert len(entities.entity_index()) == 1
    assert result['related_items'] == 3
    assert authenticated_client.post(url, json=payload).json() == result
    stored = consolidation.load(run['id'])
    assert consolidation.view(stored)['counts'] == dict(pending=0, merged=2, deferred=0, separate=0, stale=1)
    event = entity_merges.history(result['operation']['entity_id'])[0]
    assert len(event['data']['members']) == 3 and event['delivery'] == 'not-required'
    entity_merges.unmerge(result['operation']['entity_id'], str(uuid4()), 'undo', 'owner')
    assert len(entities.entity_index()) == 3


def test_group_rejects_conflicting_leaf_external_ids(alias_group, monkeypatch):
    run, payload = alias_group
    live = consolidation.current_entities()
    leaves = [e for e in live if e['id'] != payload['anchor_id']]
    for i, e in enumerate(leaves):
        e['external_id'] = f'distinct-person-{i}'
    stored = consolidation.load(run['id'])
    for e in live:
        stored['snapshots'][e['id']] = consolidation.signature(e)
    for p in stored['pairs'].values():
        for side in ['left', 'right']:
            p[side] = consolidation.evidence(next(e for e in live if e['id'] == p[side]['id']))
    consolidation.save(stored)
    monkeypatch.setattr(consolidation, 'current_entities', lambda: live)
    with pytest.raises(ValueError, match='external'):
        consolidation.merge_group(run['id'], payload)
    assert len(entities.entity_index()) == 3


def test_group_reports_count_unique_operations_not_approved_edges(alias_group, monkeypatch):
    from workflows.hfl.tasks import entity_consolidation as delivery
    from workflows.hfl import persistence
    from workflows.hfl.tasks import activity_radar
    run, payload = alias_group
    consolidation.merge_group(run['id'], payload)
    consolidation.finish(run['id'])
    assert '1 merged groups; 3 comparisons' in consolidation.report(consolidation.load(run['id']))
    monkeypatch.setattr(persistence, 'submit_hfl_entry', lambda *a, **k: {'url': 'https://corpus/group'})
    monkeypatch.setattr(activity_radar, 'corpus_document_url', lambda *a, **k: 'https://corpus/group')
    sent = []
    monkeypatch.setattr(activity_radar, '_notify', lambda text: sent.append(text) or [1])
    delivery.deliver(run['id'])
    assert 'people: 1 merged groups' in sent[0]


def test_compact_packet_preserves_evidence_and_pair_orientation(alias_group):
    run, _ = alias_group
    packet = consolidation.compact_view(run)
    assert len(packet['entities']) == 3
    assert packet['format'] == 'anchor-packets-v1'
    for original in run['pairs']:
        pair = next(p for p in packet['pairs'] if p['id'] == original['id'])
        assert packet['entities'][pair['left_id']] == original['left']
        assert packet['entities'][pair['right_id']] == original['right']
    groups = packet['groups']
    assert len(groups) == 1 and len(groups[0]['pair_ids']) == 2
    assert len(packet['ungrouped_pair_ids']) == 1
    assert len(json.dumps(packet)) < len(json.dumps(run))


@pytest.mark.parametrize('failure', ['uncorroborated', 'contradiction', 'group-conflict', 'stale', 'blocked-leaves', 'separate-leaves', 'wrong-anchor', 'closed'])
def test_group_fails_closed_without_partial_merges(alias_group, failure):
    run, payload = alias_group
    stored = consolidation.load(run['id'])
    pair_id = next(iter(payload['decisions']))
    if failure == 'uncorroborated':
        payload['decisions'][pair_id]['facts'] = []
    elif failure == 'contradiction':
        payload['decisions'][pair_id]['contradictions'] = ['Different identities']
    elif failure == 'group-conflict':
        payload['contradictions'] = ['Leaves have incompatible identifying details']
    elif failure == 'stale':
        stored['snapshots'][payload['anchor_id']] = 'old'
        consolidation.save(stored)
    elif failure in {'blocked-leaves', 'separate-leaves'}:
        leaf_pair = next(p for p in stored['pairs'].values() if payload['anchor_id'] not in p['ids'])
        if failure == 'blocked-leaves':
            with get_store().connection() as db:
                entity_matching.block_members(db, leaf_pair['ids'], 'unmerged')
        else:
            consolidation.decide(run['id'], leaf_pair['id'], decision() | {'decision': 'separate', 'facts': []})
    elif failure == 'wrong-anchor':
        payload['anchor_id'] = 'not-a-member'
    elif failure == 'closed':
        stored['state'] = 'complete'
        consolidation.save(stored)
    with pytest.raises(ValueError):
        consolidation.merge_group(run['id'], payload)
    assert len(entities.entity_index()) == 3
    with get_store().connection() as db:
        assert db.execute('SELECT count(*) FROM entity_operations').fetchone()[0] == 0


def test_group_receipt_recovers_after_commit_before_save(alias_group, monkeypatch):
    run, payload = alias_group
    save = consolidation.save
    def fail(_):
        raise RuntimeError('lost run save')
    monkeypatch.setattr(consolidation, 'save', fail)
    with pytest.raises(RuntimeError, match='lost run save'):
        consolidation.merge_group(run['id'], payload)
    assert len(entities.entity_index()) == 1
    monkeypatch.setattr(consolidation, 'save', save)
    result = consolidation.merge_group(run['id'], payload)
    assert result == consolidation.merge_group(run['id'], payload)
    assert consolidation.view(consolidation.load(run['id']))['pending_total'] == 0
    with get_store().connection() as db:
        assert db.execute('SELECT count(*) FROM entity_operations').fetchone()[0] == 1
    payload['decisions'][next(iter(payload['decisions']))]['reason'] = 'Changed approval'
    with pytest.raises(ValueError, match='different operation'):
        consolidation.merge_group(run['id'], payload)


def test_group_api_requires_explicit_cross_member_check(alias_group, authenticated_client):
    run, payload = alias_group
    payload.pop('contradictions')
    response = authenticated_client.post('/api/hfl/entities/consolidation/' + run['id'] + '/groups', json=payload)
    assert response.status_code == 422
    assert len(entities.entity_index()) == 3


def test_compact_api_is_opt_in_bounded_and_has_explicit_capability(alias_group, authenticated_client):
    run, _ = alias_group
    url = '/api/hfl/entities/consolidation/' + run['id']
    raw = authenticated_client.get(url).json()
    assert 'left' in raw['pairs'][0]
    compact = authenticated_client.get(url, params={'compact': True, 'limit': 2}).json()
    assert compact['format'] == 'anchor-packets-v1'
    assert 'atomic-anchor-groups-v1' in compact['capabilities']
    assert len(compact['pairs']) == 2 and compact['pending_total'] == 3
    assert authenticated_client.get(url, params={'limit': 21}).status_code == 422
    assert authenticated_client.post('/api/hfl/entities/consolidation/begin?compact=true').json()['format'] == 'anchor-packets-v1'


def test_group_rejects_store_change_during_snapshot_read(alias_group, monkeypatch):
    run, payload = alias_group
    read = consolidation.current_entities
    def race():
        live = read()
        with get_store().connection() as db:
            db.execute('INSERT INTO profiles(id,kind,data) VALUES (?,?,?)',
                       (payload['anchor_id'], 'people', json.dumps({
                           'name': next(e['label'] for e in live if e['id'] == payload['anchor_id']),
                           'notes': 'New owner evidence'})))
        return live
    monkeypatch.setattr(consolidation, 'current_entities', race)
    with pytest.raises(ValueError, match='changed'):
        consolidation.merge_group(run['id'], payload)
    assert len(entities.entity_index()) == 3


@pytest.mark.parametrize('mode', ['one-curated', 'two-curated', 'preferred-conflict'])
def test_group_protects_curated_profiles(alias_group, monkeypatch, mode):
    run, payload = alias_group
    live = consolidation.current_entities()
    anchor = next(e for e in live if e['id'] == payload['anchor_id'])
    other = next(e for e in live if e['id'] != anchor['id'])
    anchor['profile'] = {'notes': 'Owner-maintained identity details'}
    if mode == 'two-curated':
        other['profile'] = {'notes': 'A different curated identity'}
    elif mode == 'preferred-conflict':
        other['profile'] = {'preferred_name': True}
    stored = consolidation.load(run['id'])
    for e in live:
        stored['snapshots'][e['id']] = consolidation.signature(e)
    consolidation.save(stored)
    monkeypatch.setattr(consolidation, 'current_entities', lambda: live)
    if mode != 'one-curated':
        with pytest.raises(ValueError, match='curated'):
            consolidation.merge_group(run['id'], payload)
        assert len(entities.entity_index()) == 3
    else:
        result = consolidation.merge_group(run['id'], payload)
        event = entity_merges.history(result['operation']['entity_id'])[0]
        assert event['data']['name'] == anchor['label']
        assert event['data']['profile']['notes'].startswith('Owner-maintained identity details')


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
    result = delivery.deliver(run['id'])
    assert result['telegram_state'] == 'sent'
    assert result['telegram_ids'] == [123]
    assert 'people: 1 merged groups' in sent[0]
    assert delivery.deliver(run['id']) == result
    assert len(sent) == len(saved) == 1
    assert len(entities.entity_index()) == 1


@pytest.mark.parametrize('outcome', ['empty', 'deferred'])
def test_no_merges_persist_hfl_without_telegram(corpus, monkeypatch, outcome):
    from workflows.hfl.tasks import entity_consolidation as delivery, activity_radar
    from workflows.hfl import persistence
    if outcome == 'empty':
        monkeypatch.setattr(entities, 'current_entries', lambda: [])
    run = consolidation.begin()
    if outcome == 'deferred':
        value = decision()
        # A proposed merge is not an actual merge when evidence is rejected.
        value['facts'][0]['left_quote'] = 'Invented evidence cannot establish the identity of these people.'
        result = consolidation.decide(run['id'], run['pairs'][0]['id'], value)
        assert result['state'] == 'deferred'
    consolidation.finish(run['id'])
    stored = consolidation.load(run['id'])
    stored['delivery']['error'] = 'PreviousPersistenceFailure'
    consolidation.save(stored)
    saved, sent = [], []
    def submit(entry, **kwargs):
        saved.append((entry, kwargs))
        return {'delivery': 'persisted', 'path': '2026-10-04.md'}
    monkeypatch.setattr(persistence, 'submit_hfl_entry', submit)
    monkeypatch.setattr(activity_radar, 'corpus_document_url', lambda *a, **k: 'https://example.test/report')
    monkeypatch.setattr(activity_radar, '_notify', lambda text: sent.append(text) or [123])
    result = delivery.deliver(run['id'])
    assert sent == []
    assert result['telegram_state'] == 'suppressed'
    assert result['hfl']['delivery'] == 'persisted'
    assert 'error' not in result
    assert consolidation.load(run['id'])['delivery'] == result
    assert delivery.deliver(run['id']) == result
    assert len(saved) == 1
    assert saved[0][1]['dedup_key'] == 'entity-consolidation:' + run['id']
    assert sent == []


def test_suppressed_delivery_is_terminal_for_finish_status_and_recovery(corpus, monkeypatch, authenticated_client):
    from workflows.hfl.tasks.entity_consolidation import deliver_entity_consolidation
    run, pair = first()
    value = decision()
    value['decision'] = 'review'
    consolidation.decide(run['id'], pair['id'], value)
    consolidation.finish(run['id'])
    stored = consolidation.load(run['id'])
    stored['delivery'] = {'hfl': {'delivery': 'persisted'}, 'telegram_state': 'suppressed', 'queued_at': 0}
    consolidation.save(stored)
    monkeypatch.setattr(deliver_entity_consolidation, 'apply_async',
                        lambda **kwargs: pytest.fail('Suppressed reports must not be queued again'))
    assert consolidation.dispatch_reports() == []
    url = '/api/hfl/entities/consolidation/' + run['id']
    for _ in range(2):
        response = authenticated_client.post(url + '/finish')
        assert response.status_code == 200
        assert response.json()['delivery'] == stored['delivery']
        status = authenticated_client.get(url)
        assert status.status_code == 200
        assert status.json()['state'] == 'complete'
        assert status.json()['delivery']['telegram_state'] == 'suppressed'
    assert consolidation.dispatch_reports() == []


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
            card.get_by_role('button', name='Update soul').click()
            dialog = page.locator('.entity-connections-dialog')
            dialog.get_by_text('Identity matching helpers', exact=True).click()
            dialog.get_by_label('Aliases (one per line)', exact=True).fill('Kevin H.\nKevin Hildgendorff')
            dialog.get_by_label('Partial matching hints (one per line)', exact=True).fill('Hildgend')
            dialog.get_by_label('Prefer this display name during automatic merges').check()
            dialog.get_by_role('button', name='Save', exact=True).click()
            playwright.expect(dialog.locator('[role=status]').first).to_contain_text('Soul saved.')
            stored = next(p for p in get_store().profiles().values() if p.get('aliases'))
            assert stored['aliases'] == ['Kevin H.', 'Kevin Hildgendorff']
            assert stored['partial_aliases'] == ['Hildgend'] and stored['preferred_name']
            page.set_viewport_size({'width': 390, 'height': 844})
            assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
            page.screenshot(path=str(tmp_path / 'aliases-mobile.png'), full_page=True)
            assert not errors
        finally:
            browser.close()
