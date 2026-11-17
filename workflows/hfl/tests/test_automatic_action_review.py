"""Offline safety regressions: temporary SQLite and model-boundary stubs only."""
import json
from datetime import date

import pytest

from workflows.hfl import timeline
from workflows.hfl.timeline_store import FollowUpStore

DAY = '2026-09-09'


def decision(candidate, **changes):
    return dict(suggestion_id=candidate['id'], decision='create', confidence='high',
                completion_check='clear', reason='Concrete new next step.', **changes)


def save_ideas(store, count=1):
    run = store.claim_period(DAY, DAY, force=True)
    store.save_suggestions(DAY, DAY, run, [dict(category='recommendations', title=f'Idea {i}',
        confidence='high', status='uncertain', expected_outcome='Check an outcome',
        source={'entry_id': f'hfl-{i}', 'path': DAY+'.md', 'date': DAY, 'title': 'Source'},
        evidence=[{'entry_id': f'hfl-{i}'}]) for i in range(count)], {})
    return store.suggestions(DAY, DAY)


def test_large_review_checks_last_chunk_before_any_write(tmp_path, monkeypatch):
    store = FollowUpStore(tmp_path / 'timeline.sqlite3')
    candidates = save_ideas(store)
    # Both comparison and evidence data independently exceed the old request bound.
    actions = [dict(id=f'action-{i}', title='Existing '+str(i), expected_outcome='x'*80000,
                    status='done', source={}) for i in range(4)]
    evidence = [{'id': f'E{i}', 'text': 'y'*80000} for i in range(4)]
    snapshot = dict(actions=actions, dismissed_ideas=[], digest='test')
    assert len(json.dumps(dict(candidates=candidates, evidence=evidence, **snapshot))) > 250000
    calls = []

    def model(payload, system, field):
        assert store.list() == []
        assert 'automatic_review' not in store.suggestion(candidates[0]['id'])
        assert len(payload) <= 250000
        parsed = json.loads(payload)
        calls.append(parsed)
        result = decision(candidates[0])
        if any(item['id'] == 'action-3' for item in parsed['existing_actions']):
            result.update(decision='duplicate', existing_action_id='action-3')
        return {'decisions': [result]}

    monkeypatch.setattr(timeline, 'model_json', model)
    result = timeline.review_actions(candidates, snapshot, evidence)
    assert len(calls) > 1
    assert result[0]['decision'] == 'duplicate'
    assert result[0]['existing_action_id'] == 'action-3'
    assert {item['id'] for call in calls for item in call['existing_actions']} == {x['id'] for x in actions}
    assert {item['id'] for call in calls for item in call['evidence']} == {x['id'] for x in evidence}


@pytest.mark.parametrize('bad', ['missing', 'duplicate_id', 'unknown', 'wrong_type', 'unknown_target', 'forward', 'self', 'missing_reason', 'bad_confidence', 'bad_completion', 'bad_reason'])
def test_invalid_batch_is_atomic_even_for_direct_store_call(tmp_path, bad):
    from workflows.hfl.automatic_action_review import AutomaticActionReviewError
    store = FollowUpStore(tmp_path / 'timeline.sqlite3')
    candidates = save_ideas(store, 2)
    decisions = [decision(item) for item in candidates]
    if bad == 'missing': decisions.pop()
    elif bad == 'duplicate_id': decisions[1] = decisions[0]
    elif bad == 'unknown': decisions[1]['suggestion_id'] = 'not-supplied'
    elif bad == 'wrong_type': decisions[1]['decision'] = []
    elif bad == 'unknown_target': decisions[1].update(decision='duplicate', existing_action_id='private-invalid-target')
    elif bad == 'forward': decisions[0].update(decision='duplicate', duplicate_suggestion_id=candidates[1]['id'])
    elif bad == 'self': decisions[1].update(decision='duplicate', duplicate_suggestion_id=candidates[1]['id'])
    elif bad == 'missing_reason': decisions[1].pop('reason')
    elif bad == 'bad_confidence': decisions[1].update(decision='defer', confidence=[])
    elif bad == 'bad_completion': decisions[1].update(decision='defer', completion_check={})
    elif bad == 'bad_reason': decisions[1].update(decision='defer', reason=[])
    before = store.automation_snapshot()
    with pytest.raises(AutomaticActionReviewError) as caught:
        store.apply_auto_decisions(candidates, decisions, before['digest'], date(2026, 9, 10))
    assert caught.value.reason == 'invalid_decisions'
    assert 'private-invalid-target' not in str(caught.value)
    assert store.automation_snapshot() == before
    assert store.list() == []


def test_failed_review_has_safe_typed_diagnostic(tmp_path):
    from workflows.hfl.automatic_action_review import AutomaticActionReviewError
    store = FollowUpStore(tmp_path / 'timeline.sqlite3')
    save_ideas(store)
    def fail(*args):
        raise AutomaticActionReviewError('oversized_record', 'planning', candidates=1)
    result = timeline.create_automatic_actions(DAY, DAY, store, [], review=fail)
    assert result['diagnostic'] == {'reason': 'oversized_record', 'stage': 'planning', 'candidates': 1}
    assert result['state'] == 'deferred'
    assert result['deferred'] == 1


def test_all_dismissed_exposes_current_eligibility_without_replay(tmp_path):
    store = FollowUpStore(tmp_path / 'timeline.sqlite3')
    items = save_ideas(store, 2)
    run = store.run_for(DAY, DAY)
    historical = {'automatic_actions': {'state': 'failed', 'created': 0, 'error': 'ValueError'}}
    store.finish_period(DAY, DAY, run['run_id'], historical)
    for item in items:
        store.mark_suggestion(item['id'], 'dismissed')
    result = timeline.create_automatic_actions(DAY, DAY, store, [], review=lambda *a: pytest.fail('No replay'))
    assert result['created'] == 0
    fresh = store.run_for(DAY, DAY)
    assert fresh['result'] == historical
    assert fresh['current_automatic_actions'] == dict(state='no_eligible_candidates', eligible=0,
        total=2, suggested=0, dismissed=2, adopted=0)
    assert store.list() == []


def test_later_batch_failure_is_partial_not_success(tmp_path):
    store = FollowUpStore(tmp_path / 'timeline.sqlite3')
    save_ideas(store, 9)
    calls = []
    def review(candidates, *args):
        calls.append(candidates)
        if len(calls) == 2:
            raise RuntimeError('private provider text')
        return [decision(item) for item in candidates]
    result = timeline.create_automatic_actions(DAY, DAY, store, [], review=review)
    assert result['state'] == 'partial'
    assert result['created'] == 8
    assert result['deferred'] == 1
    assert result['diagnostic']['reason'] == 'unexpected_error'
    assert 'private provider text' not in json.dumps(result)


@pytest.mark.parametrize('kind', ['candidates', 'record', 'budget'])
def test_planning_failure_precedes_any_provider_call(tmp_path, monkeypatch, kind):
    from workflows.hfl import automatic_action_review as review
    store = FollowUpStore(tmp_path / 'timeline.sqlite3')
    candidates = save_ideas(store)
    snapshot = store.automation_snapshot()
    evidence = []
    if kind == 'candidates':
        candidates[0]['body'] = 'x' * 250000
    elif kind == 'record':
        evidence = [{'text': 'x' * 250000}]
    else:
        monkeypatch.setattr(review, 'MAX_REVIEW_SHARDS', 2)
        evidence = [{'text': 'x' * 140000} for _ in range(3)]
    monkeypatch.setattr(timeline, 'model_json', lambda *a: pytest.fail('Preflight must finish first'))
    with pytest.raises(review.AutomaticActionReviewError) as caught:
        timeline.review_actions(candidates, snapshot, evidence)
    assert caught.value.reason == {'candidates': 'oversized_candidates', 'record': 'oversized_record',
                                   'budget': 'review_budget_exhausted'}[kind]
    assert store.automation_snapshot() == snapshot


def test_late_malformed_shard_prevents_batch_writes(tmp_path, monkeypatch):
    store = FollowUpStore(tmp_path / 'timeline.sqlite3')
    items = save_ideas(store, 2)
    before = store.automation_snapshot()
    calls = []
    def model(payload, *args):
        calls.append(payload)
        assert store.automation_snapshot() == before
        return {'decisions': [decision(item) for item in items] if len(calls) == 1 else []}
    monkeypatch.setattr(timeline, 'model_json', model)
    result = timeline.create_automatic_actions(DAY, DAY, store,
        [{'text': 'x' * 140000}, {'text': 'y' * 140000}])
    assert len(calls) == 2
    assert result['state'] == 'failed'
    assert result['diagnostic']['reason'] == 'invalid_decisions'
    assert store.automation_snapshot() == before


def test_owner_dismissal_during_review_fails_closed(tmp_path):
    store = FollowUpStore(tmp_path / 'timeline.sqlite3')
    items = save_ideas(store, 2)
    def review(candidates, *args):
        store.mark_suggestion(items[-1]['id'], 'dismissed')
        return [decision(item) for item in candidates]
    result = timeline.create_automatic_actions(DAY, DAY, store, [], review=review)
    assert result['diagnostic'] == {'reason': 'snapshot_conflict', 'stage': 'commit'}
    assert result['created'] == 0
    assert store.list() == []
    assert store.suggestion(items[-1]['id'])['status'] == 'dismissed'
    assert store.suggestion(items[0]['id'])['status'] == 'suggested'


def test_dismissed_comparison_in_last_shard_and_defer_veto(tmp_path, monkeypatch):
    store = FollowUpStore(tmp_path / 'timeline.sqlite3')
    candidates = save_ideas(store)
    snapshot = dict(actions=[], dismissed_ideas=[{'id': 'dismissed-1', 'title': 'x'*140000}])
    calls = []
    def model(payload, *args):
        parsed = json.loads(payload)
        calls.append(parsed)
        value = decision(candidates[0])
        if parsed['dismissed_ideas']:
            value.update(decision='duplicate', duplicate_suggestion_id='dismissed-1')
        else:
            value.update(decision='defer', completion_check='uncertain')
        return {'decisions': [value]}
    monkeypatch.setattr(timeline, 'model_json', model)
    result = timeline.review_actions(candidates, snapshot, [{'text': 'y'*140000}])
    assert len(calls) == 2
    assert calls[-1]['dismissed_ideas'][0]['id'] == 'dismissed-1'
    assert result[0]['decision'] == 'defer'


def test_candidate_budget_reports_partial_and_remaining(tmp_path):
    store = FollowUpStore(tmp_path / 'timeline.sqlite3')
    save_ideas(store, 41)
    result = timeline.create_automatic_actions(DAY, DAY, store, [],
        review=lambda candidates, *a: [decision(item) for item in candidates])
    assert result['state'] == 'partial'
    assert result['created'] == 40
    assert result['deferred'] == 1
    assert result['diagnostic']['reason'] == 'candidate_budget_exhausted'
    assert store.run_for(DAY, DAY)['current_automatic_actions']['eligible'] == 1


def test_direct_store_ineligible_candidate_rejects_entire_batch(tmp_path):
    from workflows.hfl.timeline_store import FollowUpConflict
    store = FollowUpStore(tmp_path / 'timeline.sqlite3')
    items = save_ideas(store, 2)
    store.mark_suggestion(items[-1]['id'], 'dismissed')
    before = store.automation_snapshot()
    with pytest.raises(FollowUpConflict):
        store.apply_auto_decisions(items, [decision(item) for item in items], before['digest'], date(2026, 9, 10))
    assert store.automation_snapshot() == before
    assert store.list() == []


