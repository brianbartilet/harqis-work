"""Backlog processing against isolated stores, including concurrent reviewers."""
from concurrent.futures import ThreadPoolExecutor

import pytest

from modules.hfl_corpus import entities
from workflows.hfl import entity_consolidation as runs, entity_consolidation_work as work
from workflows.hfl.entity_evidence import select_activity
from workflows.hfl.entity_store import get_store
from test_entity_consolidation import corpus, alias_group, decision, first, FACT  # noqa: F401


def test_fifth_claim_selects_oldest_and_recovery_keeps_turn(alias_group):
    run, _ = alias_group
    stored = runs.load(run['id'])
    identities = sorted({i for p in stored['pairs'].values() for i in p['ids']})
    for pair in stored['pairs'].values():
        pair['queued_at'] = 1 if identities[0] not in pair['ids'] else 100
    stored['claim_sequence'] = 4
    runs.save(stored)
    packet = work.claim_work(run['id'], {'worker_id': 'fairness', 'max_pairs': 1})
    assert packet['claim']['anchor_id'] == identities[1]
    assert packet['pairs'][0]['queued_at'] == 1
    assert runs.load(run['id'])['claim_sequence'] == 5
    recovered = work.claim_work(run['id'], {'worker_id': 'fairness', 'max_pairs': 1})
    assert recovered['claim']['token'] == packet['claim']['token']
    assert runs.load(run['id'])['claim_sequence'] == 5


def test_old_run_refreshes_discovery_version_once(corpus, monkeypatch):
    run, _ = first()
    stored = runs.load(run['id'])
    stored.pop('discovery_version')
    runs.save(stored)
    calls = []
    original = work.discover
    def discover(run, live, signatures, seeds, index=None):
        calls.append(set(seeds))
        return original(run, live, signatures, seeds, index)
    monkeypatch.setattr(work, 'discover', discover)
    work.checkpoint(run['id'])
    assert calls[0] == set(runs.load(run['id'])['snapshots'])
    work.checkpoint(run['id'])
    assert calls[1] == set()


def test_batch_loads_and_saves_once_with_partial_errors(alias_group, monkeypatch):
    run, _ = alias_group
    calls = []
    load, save = runs.load, runs.save
    monkeypatch.setattr(runs, 'load', lambda key: calls.append('load') or load(key))
    monkeypatch.setattr(runs, 'save', lambda row: calls.append('save') or save(row))
    decisions = {p['id']: decision() | {'decision': 'review'} for p in run['pairs']}
    decisions['missing'] = decision()
    result = runs.decide_batch(run['id'], decisions)
    assert calls == ['load', 'save']
    assert [r.get('state') for r in result['results'][:-1]] == ['deferred'] * 3
    assert 'error' in result['results'][-1]
    assert load(run['id'])['pairs'][run['pairs'][0]['id']]['state'] == 'deferred'


def test_pair_merge_invalidates_consumed_endpoints_and_replays(alias_group):
    run, _ = alias_group
    pair = run['pairs'][0]
    result = runs.decide(run['id'], pair['id'], decision())
    assert result['state'] == 'merged'
    assert runs.view(runs.load(run['id']))['counts']['stale'] == 2
    assert runs.decide(run['id'], pair['id'], decision())['operation'] == result['operation']


def test_batch_recovers_commit_before_save_failure(corpus, monkeypatch):
    run, pair = first()
    save = runs.save
    monkeypatch.setattr(runs, 'save', lambda _: (_ for _ in ()).throw(RuntimeError('lost checkpoint')))
    payload = {pair['id']: decision()}
    with pytest.raises(RuntimeError, match='checkpoint'):
        runs.decide_batch(run['id'], payload)
    monkeypatch.setattr(runs, 'save', save)
    result = runs.decide_batch(run['id'], payload)
    assert result['results'][0]['state'] == 'merged'
    with get_store().connection() as db:
        assert db.execute('SELECT count(*) FROM entity_operations').fetchone()[0] == 1


def test_pair_commit_detects_snapshot_read_race(corpus, monkeypatch):
    run, pair = first()
    read = runs.current_entities
    def racing_read():
        rows = read()
        get_store().save_profile(pair['ids'][0], 'people', {'name': 'Changed owner name'})
        return rows
    monkeypatch.setattr(runs, 'current_entities', racing_read)
    result = runs.decide_batch(run['id'], {pair['id']: decision()})
    assert 'changed' in result['results'][0]['error']
    assert runs.load(run['id'])['pairs'][pair['id']]['state'] == 'pending'
    with get_store().connection() as db:
        assert db.execute('SELECT count(*) FROM entity_operations').fetchone()[0] == 0


def test_directory_capture_is_provenance_not_corroboration(corpus):
    for row in corpus:
        row.update(source='desktop', title='HARQIS entity directory')
        mention = entities.mention(row, 'people', 'Kevin Hildgendarff', FACT, 'model-extracted')
        get_store().save(row['id'], entities.entry_hash(row), [mention])
    run, pair = first()
    assert not pair['left']['activity']
    assert pair['left']['excluded_activity'][0]['source'] == 'desktop'
    assert runs.decide(run['id'], pair['id'], decision())['state'] == 'deferred'


def test_directory_only_candidates_are_not_issued_to_reviewers(corpus):
    for row in corpus:
        row.update(source='desktop', title='HARQIS entity directory')
        mention = entities.mention(row, 'people', 'Kevin Hildgendarff', FACT, 'model-extracted')
        get_store().save(row['id'], entities.entry_hash(row), [mention])
    run, _ = first()
    packet = work.claim_work(run['id'], {'worker_id': 'a'})
    assert packet['claim'] is None
    assert packet['counts']['deferred'] == 1
    assert packet['pending_total'] == 0


def test_diverse_evidence_precedes_repeated_recent_captures():
    rows = [dict(id=str(i), evidence=FACT, source='capture', date='2026-10-01') for i in range(12)]
    rows += [dict(id='older', evidence='An older independent identifying event with another project owner.',
                  source='notes', date='2020-01-01')]
    chosen, excluded, count = select_activity(rows, limit=2)
    assert {r['source'] for r in chosen} == {'capture', 'notes'}
    assert count == 13 and not excluded


def test_two_quotes_from_one_origin_are_not_two_independent_facts(corpus):
    _, pair = first()
    second = 'Kevin presented the incident review for account ZX42 in Singapore.'
    pair['signals'] = {'exact': False, 'fuzzy': .81, 'contact': False}
    for side in ('left', 'right'):
        pair[side]['activity'] = [dict(id='one', origin_id='same-capture', text=FACT + ' ' + second)]
    proposal = decision()
    proposal['facts'].append(dict(left_quote=second, right_quote=second, explanation='Different incident detail'))
    assert not runs.corroborated(proposal, pair)
    for side in ('left', 'right'):
        pair[side]['activity'] = [dict(id='one', origin_id='one', text=FACT),
                                  dict(id='two', origin_id='two', text=second)]
    assert runs.corroborated(proposal, pair)
    proposal['facts'][1]['left_entry_id'] = 'one'
    assert not runs.corroborated(proposal, pair)


def test_claim_resumes_same_worker_and_blocks_unclaimed_writes(alias_group):
    run, _ = alias_group
    packet = work.claim_work(run['id'], {'worker_id': 'worker-a'})
    claim = packet['claim']
    assert claim['token'] == work.claim_work(run['id'], {'worker_id': 'worker-a'})['claim']['token']
    waiting = work.claim_work(run['id'], {'worker_id': 'worker-b'})
    assert waiting['claim'] is None and waiting['waiting']
    pair_id = claim['pair_ids'][0]
    with pytest.raises(ValueError, match='another reviewer'):
        runs.decide(run['id'], pair_id, decision())
    result = runs.decide_batch(run['id'], {pair_id: decision() | {'decision': 'review'}}, claim['token'])
    assert result['results'][0]['state'] == 'deferred'


def test_claim_expiry_renewal_and_identical_merge_recovery(alias_group, monkeypatch):
    run, _ = alias_group
    now = work.time.time()
    monkeypatch.setattr(work.time, 'time', lambda: now)
    packet = work.claim_work(run['id'], {'worker_id': 'a', 'lease_seconds': 60})
    claim = packet['claim']
    now += 61
    with pytest.raises(ValueError, match='expired'):
        work.update_claim(run['id'], claim['token'], 'renew')
    result = runs.decide_batch(run['id'], {claim['pair_ids'][0]: decision()}, claim['token'])
    assert 'expired' in result['results'][0]['error']
    fresh = work.claim_work(run['id'], {'worker_id': 'b'})['claim']
    assert fresh['token'] != claim['token']
    payload = dict(anchor_id=fresh['anchor_id'], contradictions=[],
                   decisions={i: decision() for i in fresh['pair_ids']})
    result = runs.merge_group(run['id'], payload, fresh['token'])
    now += 4000
    assert runs.merge_group(run['id'], payload, fresh['token']) == result


def test_parallel_claims_do_not_overlap(alias_group):
    run, _ = alias_group
    with ThreadPoolExecutor(max_workers=2) as pool:
        packets = list(pool.map(lambda name: work.claim_work(run['id'], {'worker_id': name}), ['a', 'b']))
    claims = [p['claim'] for p in packets if p['claim']]
    assert len(claims) == 1


def test_independent_groups_can_be_reviewed_concurrently(corpus):
    for i, name in enumerate(['Nora Bell', 'Nora Belle'], start=2):
        row = dict(corpus[0], id=f'entry-{i}', anchor=str(i))
        corpus.append(row)
        mention = entities.mention(row, 'people', name, FACT, 'model-extracted')
        get_store().save(row['id'], entities.entry_hash(row), [mention])
    run = runs.begin()
    with ThreadPoolExecutor(max_workers=2) as pool:
        packets = list(pool.map(lambda name: work.claim_work(run['id'], {'worker_id': name}), ['a', 'b']))
    a, b = [p['claim'] for p in packets]
    assert a and b
    assert set(a['entity_ids']).isdisjoint(b['entity_ids'])


def test_anchor_neighborhood_is_selected_before_packet_limit(monkeypatch):
    live = {str(i): dict(id=str(i), label='Alex Name', kind='people', profile={},
                        entries=[dict(id=f'e-{i}', evidence=FACT, source='notes')]) for i in range(26)}
    live['0']['entries'] *= 2
    monkeypatch.setattr(runs, 'current_entities', lambda: list(live.values()))
    snapshots = {i: runs.signature(e) for i, e in live.items()}
    pairs = {}
    for i in range(1, 26):
        pair = dict(id=f'p{i:02}', ids=['0', str(i)], state='pending', kind='people',
                    left=runs.evidence(live['0']), right=runs.evidence(live[str(i)]),
                    signals={'exact': True, 'fuzzy': 1, 'contact': False}, preferred_id='0')
        pair['left']['related_items'] = 100
        pairs[pair['id']] = pair
    run = dict(id='synthetic', state='running', initial=True, delivery={},
               snapshots=snapshots, discovery_snapshots=snapshots.copy(), pairs=pairs)
    runs.save(run)
    packet = work.claim_work('synthetic', {'worker_id': 'a', 'max_pairs': 8})
    assert len(packet['pairs']) == 8
    assert packet['claim']['remaining_for_anchor'] == 17
    assert all('0' in pair['ids'] for pair in packet['pairs'])


def test_claim_packet_budget_does_not_truncate_evidence(alias_group):
    run, _ = alias_group
    stored = runs.load(run['id'])
    for pair in stored['pairs'].values():
        for side in ('left', 'right'):
            pair[side]['profile']['notes'] = 'x' * 6000
    runs.save(stored)
    result = work.claim_work(run['id'], {'worker_id': 'a', 'max_bytes': 4096})
    assert result['claim'] is None and result['required_bytes'] > 4096
    assert not runs.load(run['id']).get('claims')
    result = work.claim_work(run['id'], {'worker_id': 'a', 'max_bytes': 100000})
    assert result['evidence_bytes'] <= 100000
    assert all(len(e['profile']['notes']) == 6000 for e in result['entities'].values())


def test_changed_entities_are_discovered_without_finishing_old_run(corpus):
    run, pair = first()
    get_store().save_profile(pair['ids'][0], 'people', {'name': pair['left']['name'], 'notes': 'New source detail'})
    result = work.checkpoint(run['id'])
    assert result['state'] == 'running' and result['counts']['stale'] == 1
    assert result['pending_total'] == 1 and result['checkpoint']['added'] == 1
    again = work.checkpoint(run['id'])
    assert again['checkpoint']['added'] == 0 and again['pending_total'] == 1
    assert runs.begin()['id'] == run['id']


def test_reverted_evidence_gets_fresh_work_without_reusing_stale_decisions(corpus):
    run, pair = first()
    for notes in ['First revision', 'Second revision', 'First revision']:
        get_store().save_profile(pair['ids'][0], 'people', {'name': pair['left']['name'], 'notes': notes})
        result = work.checkpoint(run['id'])
        assert result['checkpoint']['added'] == 1 and result['pending_total'] == 1
    pending = [p for p in runs.load(run['id'])['pairs'].values() if p['state'] == 'pending']
    assert len(pending) == 1 and 'decision' not in pending[0]


def test_claim_automatically_checkpoints_and_discovers_new_entities(corpus):
    run, pair = first()
    get_store().save_profile(pair['ids'][0], 'people', {'name': pair['left']['name'], 'notes': 'Updated'})
    packet = work.claim_work(run['id'], {'worker_id': 'a'})
    assert packet['checkpoint']['added'] == 1
    assert pair['id'] not in packet['claim']['pair_ids']


def test_claim_discovers_fresh_candidate_after_partial_merge(alias_group):
    run, _ = alias_group
    runs.decide(run['id'], run['pairs'][0]['id'], decision())
    packet = work.claim_work(run['id'], {'worker_id': 'a'})
    assert packet['claim'] is not None
    assert any(i.startswith('merged-') for i in packet['claim']['entity_ids'])
    assert not set(packet['claim']['pair_ids']).intersection(p['id'] for p in run['pairs'])


def test_hydrated_original_evidence_is_shared_and_quote_checked(alias_group):
    run, _ = alias_group
    claim = work.claim_work(run['id'], {'worker_id': 'a'})['claim']
    anchor = claim['anchor_id']
    stored = runs.load(run['id'])
    evidence = next(p[side] for p in stored['pairs'].values() for side in ('left', 'right') if p[side]['id'] == anchor)
    entry_id = evidence['activity'][0]['id']
    result = work.expand_evidence(run['id'], anchor, [entry_id], claim['token'])
    assert result['activity'][0]['expanded'] and result['activity'][0]['locator']
    after = runs.load(run['id'])
    snapshots = [p[side] for p in after['pairs'].values() for side in ('left', 'right') if p[side]['id'] == anchor]
    assert all(e == result for e in snapshots)
    with pytest.raises(ValueError, match='supporting evidence'):
        work.expand_evidence(run['id'], anchor, ['unknown'], claim['token'])


def test_discovery_reuses_hydrated_evidence_for_unchanged_anchor(alias_group, corpus):
    run, _ = alias_group
    claim = work.claim_work(run['id'], {'worker_id': 'a'})['claim']
    anchor = claim['anchor_id']
    packet = work.claim_work(run['id'], {'worker_id': 'a'})
    entry_id = packet['entities'][anchor]['activity'][0]['id']
    expected = work.expand_evidence(run['id'], anchor, [entry_id], claim['token'])
    row = dict(corpus[0], id='new-neighbor', anchor='new')
    corpus.append(row)
    mention = entities.mention(row, 'people', 'Kevin Hildgendarf', FACT, 'model-extracted')
    get_store().save(row['id'], entities.entry_hash(row), [mention])
    work.checkpoint(run['id'])
    stored = runs.load(run['id'])
    evidence = [p[side] for p in stored['pairs'].values() if p['state'] == 'pending'
                for side in ('left', 'right') if p[side]['id'] == anchor]
    assert len(evidence) >= 3 and all(e == expected for e in evidence)
    work.update_claim(run['id'], claim['token'], 'release')
    assert work.claim_work(run['id'], {'worker_id': 'a'})['claim']


def test_source_edit_invalidates_hydration(corpus):
    run, pair = first()
    entry_id = pair['left']['activity'][0]['id']
    next(row for row in corpus if row['id'] == entry_id)['text'] += ' Revised identifying context.'
    with pytest.raises(ValueError, match='changed'):
        work.expand_evidence(run['id'], pair['left']['id'], [pair['left']['activity'][0]['id']])


def test_claim_api_owner_checks_and_bounds(alias_group, authenticated_client):
    run, _ = alias_group
    url = '/api/hfl/entities/consolidation/' + run['id']
    assert authenticated_client.post(url + '/claims', json={'worker_id': 'a', 'max_pairs': 21}).status_code == 422
    packet = authenticated_client.post(url + '/claims', json={'worker_id': 'a'}).json()
    claim = packet['claim']
    assert authenticated_client.post(url + '/claims/' + claim['token'], json={'action': 'renew'}).status_code == 200
    assert authenticated_client.post(url + '/claims/' + claim['token'], json={'action': 'release'}).status_code == 200
    assert authenticated_client.post(url + '/checkpoint').json()['state'] == 'running'
    authenticated_client.cookies.clear()
    for endpoint, payload in [('claims', {'worker_id': 'b'}), ('checkpoint', {}),
                              ('evidence', {'entity_id': 'x', 'entry_ids': ['x']})]:
        assert authenticated_client.post(url + '/' + endpoint, json=payload).status_code in {401, 403}
