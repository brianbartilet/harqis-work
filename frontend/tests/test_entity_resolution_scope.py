"""Avoid paid re-analysis without accepting stale or newly ambiguous identities."""
import json

import pytest

from modules.hfl_corpus import entities
from workflows.hfl import entity_resolution as resolver, entity_matching as matching
from workflows.hfl.entity_store import get_store
from workflows.hfl.entity_resolution_scope import enqueue_affected


@pytest.fixture
def corpus(monkeypatch):
    # These tests exercise the explicitly enabled historical reassessment policy.
    monkeypatch.setenv('HARQIS_ENTITY_REASSESS_HISTORY', '1')
    monkeypatch.setenv('HARQIS_ENTITY_AUTO_MATCH', '1')
    monkeypatch.setattr(matching, 'dispatch_pending', lambda: None)
    fact = 'Brian led the Mercury migration with Priya in Singapore during March 2025.'
    rows = [dict(id=i, title='Activity', text=text, source='notes', date='2026-10-20',
                 tags=[], path='day.md', anchor='', ref='') for i, text in
            [('source', fact), ('known', fact), ('unrelated', 'Zelda designed a woodland garden.')]]
    monkeypatch.setattr(entities, 'current_entries', lambda context='': list(rows))
    store = get_store()
    store.save_profile('brian', 'people', dict(name='Brian Bartilet', aliases=['Brian']))
    store.save_profile('zelda', 'people', dict(name='Zelda Fitzgerald'))
    mentions = {}
    for row in rows:
        mention = entities.mention(row, 'people', 'Zelda' if row['id'] == 'unrelated' else 'Brian',
                                   row['text'], 'model-extracted')
        if row['id'] == 'known':
            mention['id'] = 'brian'
        mentions[row['id']] = mention
        store.save(row['id'], entities.entry_hash(row), [mention], match=True)
    with store.connection() as db:
        db.execute("DELETE FROM entity_resolution_jobs WHERE entry_id!='source'")
    calls = []

    def evaluate(pairs, **kwargs):
        calls.append([p['id'] for p in pairs])
        return ([dict(id=p['id'], decision='merge', reason='Shared specific event', contradictions=[],
                      facts=[dict(left_quote=fact, right_quote=fact, explanation='Mercury migration with Priya')])
                 for p in pairs], 'test-model')
    monkeypatch.setattr(matching, 'evaluate', evaluate)
    return store, rows, mentions, calls, evaluate


def test_unrelated_edit_during_model_call_can_commit(corpus, monkeypatch):
    store, rows, mentions, calls, evaluate = corpus

    def concurrent(pairs, **kwargs):
        store.save_profile('zelda', 'people', dict(name='Zelda Fitzgerald', notes='Garden designer'))
        return evaluate(pairs, **kwargs)
    monkeypatch.setattr(matching, 'evaluate', concurrent)
    resolver.process_batch(entry_id='source')
    assert len(calls) == 1
    with store.connection() as db:
        row = db.execute("SELECT target_id FROM entity_resolutions WHERE entry_id='source'").fetchone()
        assert row['target_id'] == 'brian'
        assert not db.execute("SELECT 1 FROM entity_resolution_jobs WHERE entry_id='source'").fetchone()


@pytest.mark.parametrize('change', ['profile', 'competitor', 'source', 'evidence', 'title', 'block', 'explicit'])
def test_relevant_concurrent_change_cannot_commit(corpus, monkeypatch, change):
    store, rows, mentions, calls, evaluate = corpus

    def concurrent(pairs, **kwargs):
        if change == 'profile':
            store.save_profile('brian', 'people', dict(name='Brian Bartilet', aliases=['Brian'], notes='Corrected'))
        elif change == 'competitor':
            store.save_profile('competitor', 'people', dict(name='Brian Smith', aliases=['Brian']))
        elif change in {'source', 'evidence'}:
            rows[0 if change == 'source' else 1]['text'] += ' Corrected.'
        elif change == 'title':
            rows[1]['title'] = 'Corrected event'
        elif change == 'explicit':
            rows.append({**rows[1], 'id': 'new-explicit'})
            monkeypatch.setattr(entities, 'explicit_mentions', lambda e: [mentions['known']] if e['id'] == 'new-explicit' else [])
        else:
            with store.connection() as db:
                matching.block_members(db, [mentions['source']['id'], 'brian'], 'unmerged')
        return evaluate(pairs, **kwargs)
    monkeypatch.setattr(matching, 'evaluate', concurrent)
    with pytest.raises(ValueError, match='changed') as caught:
        resolver.process_batch(entry_id='source')
    assert type(caught.value).__name__ == 'EntityResolutionConflict'
    assert caught.value.diagnostics == dict(stage='commit', reason=(
        'state-changed' if change in {'profile', 'competitor', 'block'} else 'evidence-changed'))
    with store.connection() as db:
        assert not db.execute("SELECT 1 FROM entity_resolution_outcomes WHERE entry_id='source'").fetchone()
        assert not db.execute("SELECT 1 FROM entity_audit WHERE action='mention-resolved'").fetchone()
        assert not db.execute("SELECT 1 FROM entity_resolutions WHERE entry_id='source'").fetchone()
        assert db.execute("SELECT 1 FROM entity_resolution_jobs WHERE entry_id='source'").fetchone()


def test_assembly_conflict_stops_before_paid_comparison(corpus, monkeypatch):
    store, _, _, calls, _ = corpus
    original = entities.entity_index

    def concurrent(*args, **kwargs):
        result = original(*args, **kwargs)
        store.save_profile('brian', 'people', dict(name='Brian Bartilet', aliases=['Brian'], notes='Corrected'))
        return result

    monkeypatch.setattr(entities, 'entity_index', concurrent)
    with pytest.raises(ValueError) as caught:
        resolver.process_batch(entry_id='source')
    assert type(caught.value).__name__ == 'EntityResolutionConflict'
    assert caught.value.diagnostics == dict(stage='assembly', reason='state-changed')
    assert calls == []
    with store.connection() as db:
        assert not db.execute('SELECT 1 FROM entity_resolutions').fetchone()
        assert not db.execute('SELECT 1 FROM entity_resolution_outcomes').fetchone()
        assert db.execute("SELECT 1 FROM entity_resolution_jobs WHERE entry_id='source'").fetchone()


def test_identity_edit_queues_only_dependent_entries(corpus):
    store, *_ = corpus
    resolver.process_batch(entry_id='source')
    with store.connection() as db:
        db.execute('DELETE FROM entity_resolution_jobs')
    store.save_profile('brian', 'people', dict(name='Brian Bartilet', aliases=['Brian'], notes='Updated'))
    with store.connection() as db:
        assert {r[0] for r in db.execute('SELECT entry_id FROM entity_resolution_jobs')} == {'source', 'known'}
        assert json.loads(db.execute("SELECT data FROM entity_resolutions WHERE entry_id='source'").fetchone()[0])['active'] is False


def test_new_competitor_reopens_a_completed_assignment(corpus):
    store, *_ = corpus
    resolver.process_batch(entry_id='source')
    store.save_profile('competitor', 'people', dict(name='Brian Smith', aliases=['Brian']))
    with store.connection() as db:
        assert db.execute("SELECT 1 FROM entity_resolution_jobs WHERE entry_id='source'").fetchone()
        assert not json.loads(db.execute("SELECT data FROM entity_resolutions WHERE entry_id='source'").fetchone()[0])['active']


def test_identical_comparisons_reused_after_requeue(corpus):
    store, rows, mentions, calls, _ = corpus
    resolver.process_batch(entry_id='source')
    with store.connection() as db:
        enqueue_affected(db, ['brian'])
    resolver.process_batch(entry_id='source')
    assert len(calls) == 1
    rows[1]['text'] += ' New event evidence.'
    mentions['known']['evidence'] = rows[1]['text']
    store.save('known', entities.entry_hash(rows[1]), [mentions['known']], match=True)
    resolver.process_batch(entry_id='source')
    assert len(calls) == 2


def test_cache_survives_later_batch_failure_and_is_model_policy_scoped(corpus, monkeypatch):
    store, _, _, calls, evaluate = corpus
    pairs = [dict(id=str(i), left={}, right={}) for i in range(9)]

    def fail_second(chunk, **kwargs):
        if chunk[0]['id'] == '8':
            raise RuntimeError('provider offline')
        return evaluate(chunk, **kwargs)
    monkeypatch.setattr(matching, 'evaluate', fail_second)
    with pytest.raises(RuntimeError):
        resolver.evaluate_cached(store, pairs)
    monkeypatch.setattr(matching, 'evaluate', evaluate)
    resolver.evaluate_cached(store, pairs)
    assert [len(c) for c in calls] == [8, 1]
    monkeypatch.setenv('HARQIS_ENTITY_MATCH_MODEL', 'another-model')
    resolver.evaluate_cached(store, pairs[:1])
    assert len(calls) == 3
    monkeypatch.setattr(resolver, 'CACHE_POLICY', 'next-policy')
    resolver.evaluate_cached(store, pairs[:1])
    assert len(calls) == 4


def test_noop_profile_save_does_not_requeue(corpus):
    store, *_ = corpus
    resolver.process_batch(entry_id='source')
    store.save_profile('brian', 'people', dict(name='Brian Bartilet', aliases=['Brian']))
    with store.connection() as db:
        assert not db.execute("SELECT 1 FROM entity_resolution_jobs WHERE entry_id='source'").fetchone()


@pytest.mark.parametrize('history', [True, False])
def test_merge_and_unmerge_do_not_queue_unrelated_entries(corpus, authenticated_client, monkeypatch, history):
    monkeypatch.setenv('HARQIS_ENTITY_REASSESS_HISTORY', '1' if history else '0')
    from uuid import uuid4
    from workflows.hfl import entity_merges
    monkeypatch.setattr(entity_merges, 'flush_audits', lambda: None)
    monkeypatch.setattr(resolver, 'dispatch_pending', lambda: None)
    store, _, mentions, *_ = corpus
    body = dict(entity_ids=['brian', mentions['source']['id']], name='Brian Bartilet')
    preview = authenticated_client.post('/api/hfl/entities/merge-preview', json=body)
    assert preview.status_code == 200, preview.text
    response = authenticated_client.post('/api/hfl/entities/merges', json={
        **body, 'request_id': str(uuid4()), 'preview_token': preview.json()['preview_token']})
    assert response.status_code == 200, response.text
    with store.connection() as db:
        assert {r[0] for r in db.execute('SELECT entry_id FROM entity_resolution_jobs')} == ({'source', 'known'} if history else {'source'})
        db.execute('DELETE FROM entity_resolution_jobs')
    response = authenticated_client.post('/api/hfl/entities/merges/' + response.json()['entity_id'] + '/unmerge',
                                         json={'request_id': str(uuid4())})
    assert response.status_code == 200, response.text
    with store.connection() as db:
        assert {r[0] for r in db.execute('SELECT entry_id FROM entity_resolution_jobs')} == ({'source', 'known'} if history else set())


def test_cached_approval_cannot_bypass_a_new_competitor(corpus, monkeypatch):
    store, _, mentions, calls, evaluate = corpus
    resolver.process_batch(entry_id='source')
    store.save_profile('competitor', 'people', dict(name='Brian Smith', aliases=['Brian']))

    def review(pairs, **kwargs):
        results, model = evaluate(pairs, **kwargs)
        for result in results:
            result.update(decision='review', facts=[])
        return results, model
    monkeypatch.setattr(matching, 'evaluate', review)
    resolver.process_batch(entry_id='source')
    assert [len(c) for c in calls] == [1, 1]  # Brian reused; only the new competitor evaluated.
    with store.connection() as db:
        assert not json.loads(db.execute("SELECT data FROM entity_resolutions WHERE entry_id='source'").fetchone()[0])['active']
        assert db.execute("SELECT outcome FROM entity_resolution_outcomes WHERE entry_id='source'").fetchone()[0] == 'ambiguous'
