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


@pytest.mark.parametrize('target, index, reason', [
    ('private invented target', 0, 'unknown ID'),
    ([], 0, 'non-string reference'),
    ('candidate:0', 0, 'self reference'),
    ('candidate:2', 0, 'forward reference'),
    ('candidate:0', 1, 'reference to a suppressed candidate'),
])
def test_invalid_target_retries_once_with_safe_diagnosis(monkeypatch, target, index, reason):
    candidates = [{'title': 'One'}, {'title': 'Two'}, {'title': 'Three'}]
    existing = [{'id': 'idea:old'}]
    decisions = [{'id': f'candidate:{i}', 'duplicate_of': 'idea:old'} for i in range(3)]
    decisions[index]['duplicate_of'] = target
    calls = []

    def model(payload, prompt, field):
        calls.append((payload, prompt))
        return {'decisions': decisions}

    monkeypatch.setattr(timeline, 'model_json', model)
    with pytest.raises(timeline.TimelineModelError, match=reason) as caught:
        timeline.review_ideas(candidates, existing)
    assert len(calls) == 2
    assert calls[0][0] == calls[1][0]
    assert reason in calls[1][1]
    assert f'candidate:{index}' in str(caught.value)
    assert 'Both duplicate-review attempts failed' in str(caught.value)
    assert 'private invented target' not in str(caught.value) + calls[1][1]


def test_corrected_review_is_validated_and_applied_as_a_whole(monkeypatch):
    candidates = [{'title': 'One'}, {'title': 'Two'}]
    responses = iter([
        {'decisions': [{'id': 'candidate:0', 'duplicate_of': 'candidate:1'},
                       {'id': 'candidate:1', 'duplicate_of': None}]},
        {'decisions': [{'id': 'candidate:0', 'duplicate_of': None},
                       {'id': 'candidate:1', 'duplicate_of': 'candidate:0'}]},
    ])
    monkeypatch.setattr(timeline, 'model_json', lambda *args: next(responses))
    assert timeline.review_ideas(candidates, []) == ([candidates[0]], 1)


def test_invalid_review_preserves_existing_cache(tmp_path, monkeypatch):
    store = FollowUpStore(tmp_path / 'ideas.sqlite3')
    day = '2026-09-01'
    seed(store, day)
    cached = store.suggestions(day, day)
    run = store.claim_period(day, day, force=True)
    monkeypatch.setattr(timeline, 'model_json', lambda *args: {
        'decisions': [{'id': 'candidate:0', 'duplicate_of': 'private invalid ID'}]})

    def review(*args):
        return timeline.review_ideas([{'title': 'New'}], [{'id': 'idea:old'}])

    with pytest.raises(timeline.TimelineModelError, match='unknown ID'):
        timeline.explore_period(day, day, run_id=run, store=store,
                               collect=lambda *args: ([], {}), idea_review=review)
    assert store.suggestions(day, day) == cached
    saved = store.run_for(day, day)
    assert saved['state'] == 'failed'
    assert 'unknown ID' in saved['result']['message']
    assert 'private invalid ID' not in json.dumps(saved)


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
