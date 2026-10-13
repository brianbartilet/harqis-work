import json

import pytest

from workflows.hfl import timeline
from workflows.hfl.timeline_store import FollowUpConflict, FollowUpStore


def test_review_suppresses_paraphrases_but_keeps_distinct_outcomes(monkeypatch):
    candidates = [{'title': 'Another export feasibility check', 'expected_outcome': 'Assess export'},
                  {'title': 'Implement export', 'expected_outcome': 'Ship export'},
                  {'title': 'Build the exporter', 'expected_outcome': 'Ship export'}]
    existing = [{'id': 'idea:old', 'title': 'Investigate export', 'outcome': 'Assess export', 'status': 'suggested'}]
    def model(payload, prompt, field):
        assert json.loads(payload)['existing_intents'] == existing
        assert 'concrete intended outcome' in prompt
        return {'decisions': [{'id': 'candidate:0', 'duplicate_of': 'idea:old'},
                              {'id': 'candidate:1', 'duplicate_of': None},
                              {'id': 'candidate:2', 'duplicate_of': 'candidate:1'}]}
    monkeypatch.setattr(timeline, 'model_json', model)
    assert timeline.review_ideas(candidates, existing) == ([candidates[1]], 2)


@pytest.mark.parametrize('decisions', [[], [{}], [{'id': 'candidate:0'}],
    [{'id': 'candidate:0', 'duplicate_of': 'unknown'}],
    [{'id': 'candidate:0', 'duplicate_of': 'candidate:0'}],
    [{'id': 'candidate:0', 'duplicate_of': []}],
    [{'id': 'candidate:99', 'duplicate_of': None}]])
def test_invalid_reviews_fail_closed(monkeypatch, decisions):
    monkeypatch.setattr(timeline, 'model_json', lambda *args: {'decisions': decisions})
    with pytest.raises(timeline.TimelineModelError):
        timeline.review_ideas([{'title': 'Proposal'}], [{'id': 'idea:old'}])


def test_no_review_call_for_empty_or_only_first_idea(monkeypatch):
    def unexpected(*args):
        pytest.fail('Unnecessary model call')
    monkeypatch.setattr(timeline, 'model_json', unexpected)
    assert timeline.review_ideas([], [{'id': 'idea:old'}]) == ([], 0)
    assert timeline.review_ideas([{'title': 'First'}], []) == ([{'title': 'First'}], 0)


def seed(store, day, title='Existing idea'):
    run = store.claim_period(day, day)
    store.save_suggestions(day, day, run, [{'title': title, 'category': 'recommendations',
        'evidence': [{'entry_id': day}], 'status': 'uncertain'}], {})
    return run


def test_snapshot_includes_owner_edits_and_dismissals(tmp_path):
    from workflows.hfl.ideas_store import IdeasStore
    store = FollowUpStore(tmp_path / 'ideas.sqlite3')
    seed(store, '2026-09-01')
    IdeasStore(store)
    identity = store.idea_generation_snapshot()['records'][0]['id'].removeprefix('idea:')
    before = store.idea_generation_snapshot()
    with store.connect() as db:
        db.execute('INSERT INTO idea_edits VALUES (?,?,?)', (identity, 1, json.dumps({'title': 'Owner wording', 'status': 'suggested'})))
    store.mark_suggestion(identity, 'dismissed')
    after = store.idea_generation_snapshot()
    assert after['digest'] != before['digest']
    assert after['records'][0]['title'] == 'Owner wording'
    assert after['records'][0]['status'] == 'dismissed'


def test_concurrent_generation_cannot_save_a_stale_review(tmp_path):
    store = FollowUpStore(tmp_path / 'ideas.sqlite3')
    seed(store, '2026-09-01')
    run = store.claim_period('2026-09-02', '2026-09-02')
    snapshot = store.idea_generation_snapshot()
    seed(store, '2026-09-03', 'Concurrent proposal')
    with pytest.raises(FollowUpConflict):
        store.save_suggestions('2026-09-02', '2026-09-02', run, [], {}, expected_idea_digest=snapshot['digest'])
    assert len(store.idea_generation_snapshot()['records']) == 2


@pytest.mark.parametrize('review_fails', [False, True])
def test_exploration_filters_before_persistence_and_passes_generation_context(tmp_path, review_fails):
    store = FollowUpStore(tmp_path / 'ideas.sqlite3')
    seed(store, '2026-09-01')
    row = {'entry_id': 'new-evidence', 'path': '2026-09-02.md', 'when': '2026-09-02T12:00:00+08:00',
           'moment': 'Another mention', 'what_happened': 'Assess export feasibility', 'source': 'notes'}
    def analyze(*args, **kwargs):
        assert kwargs['existing_intents'][0]['title'] == 'Existing idea'
        return {'findings': [{'category': 'recommendations', 'title': 'Rephrased idea', 'severity': 'low',
            'confidence': 'medium', 'status': 'uncertain', 'observation': 'Another mention',
            'inference': 'May still be useful', 'recommendation': 'Assess export feasibility',
            'evidence': ['N1'], 'latest_evidence': ['N1'], 'resolution_check': 'No new outcome'}]}
    def review(candidates, existing):
        assert len(candidates) == len(existing) == 1
        if review_fails:
            raise timeline.TimelineModelError('Duplicate review unavailable')
        return [], 1
    kwargs = dict(store=store, collect=lambda *args: ([row], {}), related=lambda *args: [], analyze=analyze, idea_review=review)
    if review_fails:
        with pytest.raises(timeline.TimelineModelError):
            timeline.explore_period('2026-09-02', '2026-09-02', **kwargs)
        assert store.run_for('2026-09-02', '2026-09-02')['state'] == 'failed'
    else:
        result = timeline.explore_period('2026-09-02', '2026-09-02', **kwargs)
        assert result['suggestions'] == 0
        assert result['duplicate_ideas_suppressed'] == 1
    assert len(store.idea_generation_snapshot()['records']) == 1
