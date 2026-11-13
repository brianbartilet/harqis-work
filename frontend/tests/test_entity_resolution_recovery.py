"""Malformed provider responses and duplicate deliveries never commit or multiply work."""
import json
import time
from types import SimpleNamespace as NS

import pytest
from filelock import FileLock

from workflows.hfl import entity_resolution as resolution
from workflows.hfl.entity_model_response import EntityModelResponseError, parse_decisions
from workflows.hfl.entity_store import get_store
from workflows.knowledge.tasks.connected_hfl import resolve_corpus_entities as task


def decision(identity='p'):
    return dict(id=identity, decision='review', reason='Insufficient evidence', contradictions=[], facts=[])


def response(text, stop='end_turn'):
    return NS(stop_reason=stop, content=[NS(type='text', text=text)],
              usage=NS(input_tokens=100, output_tokens=40))


def test_parser_handles_fences_and_multiple_text_blocks():
    body = json.dumps({'decisions': [decision()]})
    message = response('```json\n' + body + '\n```')
    assert parse_decisions(message, ['p']) == [decision()]
    message.content = [NS(type='thinking'), NS(type='text', text=body[:20]), NS(type='text', text=body[20:])]
    assert parse_decisions(message, ['p']) == [decision()]


@pytest.mark.parametrize('body,stop,reason', [
    ('{"decisions":', 'max_tokens', 'truncated'),
    ('private source text and provider secret', 'end_turn', 'invalid-json'),
    ('[]', 'end_turn', 'invalid-decision-list'),
    ('{}', 'refusal', 'incomplete-response'),
    ('{"decisions":[]}', 'end_turn', 'missing-decisions'),
    (json.dumps({'decisions': [decision(), decision()]}), 'end_turn', 'duplicate-decision-id'),
    (json.dumps({'decisions': [decision('unknown')]}), 'end_turn', 'unexpected-decision-id'),
    (json.dumps({'decisions': [decision(None)]}), 'end_turn', 'missing-decision-id'),
    (json.dumps({'decisions': [{**decision(), 'facts': [None]}]}), 'end_turn', 'invalid-fact'),
    (json.dumps({'decisions': [{**decision(), 'decision': 'approve'}]}), 'end_turn', 'invalid-decision'),
])
def test_parser_rejects_incomplete_or_invalid_output_without_payload(body, stop, reason):
    with pytest.raises(EntityModelResponseError) as caught:
        parse_decisions(response(body, stop), ['p'])
    assert caught.value.diagnostics['reason'] == reason
    assert 'private source' not in str(caught.value)
    assert 'provider secret' not in json.dumps(caught.value.diagnostics)
    if reason == 'invalid-json':
        assert caught.value.diagnostics['line'] == 1
        assert caught.value.diagnostics['position'] == 0


@pytest.fixture
def queue(monkeypatch, tmp_path):
    monkeypatch.setenv('HARQIS_ENTITIES_DB', str(tmp_path / 'resolution.sqlite3'))
    monkeypatch.setenv('HARQIS_ENTITY_AUTO_MATCH', '1')
    store = get_store()
    with store.connection() as db:
        db.execute("INSERT INTO entity_resolution_jobs(entry_id,revision) VALUES ('entry','v1')")
    from core.apps.sprout.app.celery import SPROUT
    sent = []
    monkeypatch.setattr(SPROUT, 'send_task', lambda *args, **kwargs: sent.append(kwargs))
    return store, sent


def test_matcher_maps_reordered_short_ids_without_changing_evidence(monkeypatch):
    from workflows.hfl import entity_matching as matching
    from apps.antropic.references.web.base_api_service import BaseApiServiceAnthropic
    pairs = [dict(id='a' * 64, left={'id': 'entity:left', 'activity': ['evidence']}, right={}),
             dict(id='b' * 64, left={}, right={'id': 'entity:right'})]
    original = json.dumps(pairs)
    def send(self, **kwargs):
        supplied = json.loads(kwargs['messages'][0]['content'])
        assert [p['id'] for p in supplied] == ['p1', 'p2']
        assert supplied[0]['left'] == pairs[0]['left']
        assert supplied[1]['right'] == pairs[1]['right']
        return response(json.dumps({'decisions': [decision('p2'), decision('p1')]}))
    monkeypatch.setattr(BaseApiServiceAnthropic, '__init__', lambda *a, **kw: None)
    monkeypatch.setattr(BaseApiServiceAnthropic, 'send_messages', send)
    result, _ = matching.evaluate(pairs, immediate=True)
    assert [d['id'] for d in result] == ['b' * 64, 'a' * 64]
    assert json.dumps(pairs) == original


@pytest.mark.parametrize('returned,reason', [
    (['entity:left'], 'unexpected-decision-id'),
    (['p1', 'p1'], 'duplicate-decision-id'),
    ([], 'missing-decisions'),
])
def test_matcher_rejects_bad_local_ids(monkeypatch, returned, reason):
    from workflows.hfl import entity_matching as matching
    from apps.antropic.references.web.base_api_service import BaseApiServiceAnthropic
    monkeypatch.setattr(BaseApiServiceAnthropic, '__init__', lambda *a, **kw: None)
    monkeypatch.setattr(BaseApiServiceAnthropic, 'send_messages', lambda *a, **kw:
                        response(json.dumps({'decisions': [decision(i) for i in returned]})))
    with pytest.raises(EntityModelResponseError) as caught:
        matching.evaluate([{'id': 'durable', 'left': {}, 'right': {}}])
    assert caught.value.diagnostics['reason'] == reason
    assert 'entity:left' not in json.dumps(caught.value.diagnostics)


def test_matcher_rejects_duplicate_inputs_before_provider_call(monkeypatch):
    from workflows.hfl import entity_matching as matching
    from apps.antropic.references.web.base_api_service import BaseApiServiceAnthropic
    monkeypatch.setattr(BaseApiServiceAnthropic, '__init__', lambda *a, **kw: pytest.fail('Paid call setup'))
    with pytest.raises(ValueError, match='Duplicate comparison IDs'):
        matching.evaluate([{'id': 'same'}, {'id': 'same'}])


def test_failure_history_is_bounded_and_survives_recovery(queue, monkeypatch):
    store, _ = queue
    store.state('resolution-error-history', [{'at': i} for i in range(100)])
    def fail(**kwargs):
        parse_decisions(response(json.dumps({'decisions': [decision('private-id')]})), ['p1'])
    monkeypatch.setattr(resolution, 'process_batch', fail)
    resolution.process_pending()
    history = store.state('resolution-error-history')
    assert len(history) == 100 and history[0] == {'at': 1}
    assert history[-1]['attempt'] == 1
    assert history[-1]['revision'] == 'v1'
    assert history[-1]['diagnostics']['reason'] == 'unexpected-decision-id'
    assert 'private-id' not in json.dumps(history)
    with store.connection() as db:
        db.execute('UPDATE entity_resolution_jobs SET next_attempt=0')
    def succeed(**kwargs):
        with store.connection() as db:
            db.execute('DELETE FROM entity_resolution_jobs')
        return {'processed': 1}
    monkeypatch.setattr(resolution, 'process_batch', succeed)
    resolution.process_pending()
    assert store.state('resolution-error:entry') is None
    assert store.state('resolution-error-history') == history


def test_dispatch_coalesces_producers_and_recovers_expired_wakeup(queue):
    store, sent = queue
    assert resolution.dispatch_pending()['state'] == 'queued'
    for _ in range(20):
        assert resolution.dispatch_pending()['state'] == 'coalesced'
    assert len(sent) == 1
    old = store.state('resolution-wakeup')
    store.state('resolution-wakeup', {**old, 'expires_at': time.time() - 1})
    resolution.dispatch_pending()
    assert len(sent) == 2
    assert sent[0]['task_id'] != sent[1]['task_id']
    assert task.run(dispatch_id=old['token']) == {'state': 'superseded'}
    assert len(sent) == 2


def test_future_backoff_and_new_ready_work_replace_wakeup(queue):
    store, sent = queue
    with store.connection() as db:
        db.execute('UPDATE entity_resolution_jobs SET next_attempt=?', (time.time() + 60,))
    resolution.dispatch_pending()
    assert 59 <= sent[0]['countdown'] <= 61
    for _ in range(20):
        assert resolution.dispatch_pending()['state'] == 'coalesced'
    with store.connection() as db:
        db.execute("INSERT INTO entity_resolution_jobs(entry_id,revision) VALUES ('new','v1')")
    resolution.dispatch_pending()
    assert len(sent) == 2 and sent[1]['countdown'] == 2
    assert task.run(dispatch_id=sent[0]['task_id']) == {'state': 'superseded'}


def test_lock_contention_never_reschedules_duplicates(queue, monkeypatch):
    store, sent = queue
    monkeypatch.setattr(task, 'apply_async', lambda **kwargs: pytest.fail('Duplicate retried itself'))
    with FileLock(str(store.path) + '.resolution.lock'):
        for _ in range(20):
            assert task.run() == {'state': 'coalesced'}
            assert resolution.dispatch_pending()['state'] == 'coalesced'
    assert sent == []
    assert resolution.dispatch_pending()['state'] == 'queued'


def test_uncertain_publish_retains_reservation_until_recovery(queue, monkeypatch):
    store, sent = queue
    from core.apps.sprout.app.celery import SPROUT
    def fail(*args, **kwargs):
        raise RuntimeError('secret broker URL')
    monkeypatch.setattr(SPROUT, 'send_task', fail)
    assert resolution.dispatch_pending()['state'] == 'dispatch-uncertain'
    assert resolution.dispatch_pending()['state'] == 'coalesced'
    assert 'secret' not in json.dumps(store.state('resolution-dispatch-error'))


def test_partial_failure_is_durable_and_celery_fails_after_scheduling(queue, monkeypatch):
    store, sent = queue
    with store.connection() as db:
        db.execute("INSERT INTO entity_resolution_jobs(entry_id,revision) VALUES ('good','v1')")
    def process(use_model=True, entry_id=None):
        if entry_id == 'entry':
            parse_decisions(response('secret source text'), ['p'])
        with store.connection() as db:
            db.execute('DELETE FROM entity_resolution_jobs WHERE entry_id=?', (entry_id,))
        return {'processed': 1}
    monkeypatch.setattr(resolution, 'process_batch', process)
    resolution.dispatch_pending()
    with pytest.raises(RuntimeError, match='1 entries failed; 1 processed'):
        task.run(dispatch_id=sent[0]['task_id'])
    assert len(sent) == 2
    result = store.state('resolution-last-result')
    assert result['state'] == 'partial-failure'
    assert result['errors'][0]['diagnostics']['reason'] == 'invalid-json'
    assert 'secret source' not in json.dumps(result)
    with store.connection() as db:
        assert db.execute('SELECT count(*) FROM entity_resolution_jobs').fetchone()[0] == 1
        assert db.execute('SELECT attempts FROM entity_resolution_jobs').fetchone()[0] == 1
    assert 29 <= sent[1]['countdown'] <= 31
    assert task.run(dispatch_id=sent[0]['task_id']) == {'state': 'superseded'}
    assert len(sent) == 2


def test_success_consumes_reservation_without_idle_continuation(queue, monkeypatch):
    store, sent = queue
    def process():
        with store.connection() as db:
            db.execute('DELETE FROM entity_resolution_jobs')
        return {'processed': 1, 'pending': 0, 'errors': []}
    monkeypatch.setattr(resolution, 'process_pending', process)
    resolution.dispatch_pending()
    assert task.run(dispatch_id=sent[0]['task_id'])['processed'] == 1
    assert store.state('resolution-wakeup') == {}
    assert len(sent) == 1


def test_unexpected_batch_failure_has_global_cooldown(queue, monkeypatch):
    store, sent = queue
    def fail():
        raise ValueError('secret provider payload')
    monkeypatch.setattr(resolution, 'process_pending', fail)
    resolution.dispatch_pending()
    with pytest.raises(RuntimeError, match='batch failed: ValueError'):
        task.run(dispatch_id=sent[0]['task_id'])
    assert len(sent) == 2
    assert 59 <= sent[1]['countdown'] <= 61
    for _ in range(20):
        assert resolution.dispatch_pending()['state'] == 'coalesced'
    assert 'secret' not in json.dumps(store.state('resolution-task-error'))


@pytest.mark.parametrize('attempts', [0, 4])
def test_snapshot_conflicts_back_off_without_spending_failure_budget(queue, monkeypatch, attempts):
    store, sent = queue
    now = [100000.0]
    monkeypatch.setattr(resolution.time, 'time', lambda: now[0])
    with store.connection() as db:
        db.execute('UPDATE entity_resolution_jobs SET attempts=?', (attempts,))
    calls = []

    def conflict(**kwargs):
        calls.append(kwargs)
        raise resolution.EntityResolutionConflict('commit', 'evidence-changed')

    monkeypatch.setattr(resolution, 'process_batch', conflict)
    for delay in [30, 60, 120, 240, 480, 960, 1920, 3600, 3600]:
        # Reload through get_store each time: cooldown is durable, not in memory.
        result = resolution.process_pending()
        assert result['errors'] == []
        assert result['state'] == 'deferred'
        assert result['processed'] == result['pending'] == 0
        assert result['conflicts'][0]['diagnostics'] == dict(stage='commit', reason='evidence-changed')
        with get_store().connection() as db:
            job = dict(db.execute('SELECT * FROM entity_resolution_jobs').fetchone())
        assert job['attempts'] == attempts and job['state'] == 'pending'
        assert job['next_attempt'] == now[0] + delay
        before = len(calls)
        resolution.process_pending()
        assert len(calls) == before  # No model churn before the durable deadline.
        now[0] += delay
    assert store.state('resolution-error-history')[-1]['attempt'] == attempts
    assert store.state('resolution-last-error') is None
    # A due conflict schedules continuation but is not a Celery FAILURE.
    resolution.dispatch_pending()
    result = task.run(dispatch_id=sent[-1]['task_id'])
    assert result['state'] == 'deferred' and result['errors'] == []
    assert sent[-1]['countdown'] == 3600


@pytest.mark.parametrize('error_type,reason', [(ValueError, 'value-error'), (RuntimeError, 'unexpected-error')])
def test_value_error_is_a_safe_bounded_hard_failure(queue, monkeypatch, error_type, reason):
    store, _ = queue
    secret = 'private source text, model response, provider credential'

    def fail(**kwargs):
        raise error_type(secret)

    monkeypatch.setattr(resolution, 'process_batch', fail)
    for attempt in range(1, 6):
        result = resolution.process_pending()
        assert result['state'] == 'failed'
        assert result['errors'][0]['diagnostics'] == dict(stage='process-batch', reason=reason)
        with store.connection() as db:
            job = dict(db.execute('SELECT * FROM entity_resolution_jobs').fetchone())
            assert job['attempts'] == attempt
            assert job['state'] == ('failed' if attempt == 5 else 'pending')
            db.execute('UPDATE entity_resolution_jobs SET next_attempt=0')
            assert secret not in json.dumps([tuple(r) for r in db.execute('SELECT * FROM state')])
    assert resolution.process_pending()['errors'] == []  # Quarantined, not attempted again.


@pytest.mark.parametrize('conflict', [True, False])
def test_failure_does_not_annotate_or_delay_replacement_revision(queue, monkeypatch, conflict):
    store, _ = queue
    replacement_details = dict(stage='replacement', reason='sentinel')

    def replace(**kwargs):
        with store.connection() as db:
            db.execute("UPDATE entity_resolution_jobs SET revision='v2',attempts=0,next_attempt=123,error='new' ")
        store.state('resolution-error:entry', replacement_details)
        if conflict:
            raise resolution.EntityResolutionConflict('assembly', 'state-changed')
        raise ValueError('private source payload')

    monkeypatch.setattr(resolution, 'process_batch', replace)
    resolution.process_pending()
    with store.connection() as db:
        job = dict(db.execute('SELECT * FROM entity_resolution_jobs').fetchone())
    assert (job['revision'], job['attempts'], job['next_attempt'], job['state'], job['error']) == (
        'v2', 0, 123, 'pending', 'new')
    assert store.state('resolution-error:entry') == replacement_details
    assert store.state('resolution-conflict:entry') is None


def test_success_clears_conflict_cooldown_but_retains_history(queue, monkeypatch):
    store, _ = queue

    def conflict(**kwargs):
        raise resolution.EntityResolutionConflict('assembly', 'state-changed')

    monkeypatch.setattr(resolution, 'process_batch', conflict)
    resolution.process_pending()
    assert store.state('resolution-conflict:entry')['count'] == 1
    history = store.state('resolution-error-history')
    with store.connection() as db:
        db.execute('UPDATE entity_resolution_jobs SET next_attempt=0')

    def succeed(**kwargs):
        with store.connection() as db:
            db.execute('DELETE FROM entity_resolution_jobs')
        return {'processed': 1}

    monkeypatch.setattr(resolution, 'process_batch', succeed)
    assert resolution.process_pending()['processed'] == 1
    assert store.state('resolution-conflict:entry') is None
    assert store.state('resolution-error:entry') is None
    assert store.state('resolution-error-history') == history


def test_success_does_not_clear_replacement_diagnostics(queue, monkeypatch):
    store, _ = queue
    sentinel = dict(revision='v2', count=3)

    def replace(**kwargs):
        with store.connection() as db:
            db.execute("UPDATE entity_resolution_jobs SET revision='v2'")
        store.state('resolution-error:entry', {'reason': 'new'})
        store.state('resolution-conflict:entry', sentinel)
        return {'processed': 1}

    monkeypatch.setattr(resolution, 'process_batch', replace)
    resolution.process_pending()
    assert store.state('resolution-conflict:entry') == sentinel
    assert store.state('resolution-error:entry') == {'reason': 'new'}


def test_conflict_preserves_last_hard_failure_and_final_failure_still_quarantines(queue, monkeypatch):
    store, sent = queue
    with store.connection() as db:
        db.execute('UPDATE entity_resolution_jobs SET attempts=4')
    previous = dict(error='ValueError', diagnostics=dict(stage='process-batch', reason='value-error'))
    store.state('resolution-last-error', previous)

    def conflict(**kwargs):
        raise resolution.EntityResolutionConflict('commit', 'state-changed')

    monkeypatch.setattr(resolution, 'process_batch', conflict)
    resolution.process_pending()
    assert store.state('resolution-last-error') == previous
    with store.connection() as db:
        db.execute('UPDATE entity_resolution_jobs SET next_attempt=0')

    def fail(**kwargs):
        raise ValueError('secret evidence text')

    monkeypatch.setattr(resolution, 'process_batch', fail)
    resolution.dispatch_pending()
    with pytest.raises(RuntimeError, match='1 entries failed; 0 processed'):
        task.run(dispatch_id=sent[0]['task_id'])
    with store.connection() as db:
        assert tuple(db.execute('SELECT attempts,state FROM entity_resolution_jobs').fetchone()) == (5, 'failed')
    assert len(sent) == 1  # No continuation for quarantined work.
    assert 'secret evidence' not in json.dumps(resolution.status())


def test_response_error_survives_celery_exception_serialization():
    import pickle
    error = EntityModelResponseError({'reason': 'truncated', 'stop_reason': 'max_tokens'})
    restored = pickle.loads(pickle.dumps(error))
    assert restored.diagnostics == error.diagnostics
    assert str(restored) == str(error)


def test_enrichment_duplicates_leave_durable_work_for_dispatcher(queue, monkeypatch):
    from types import SimpleNamespace
    from workflows.hfl import entity_events, entity_matching
    from workflows.knowledge.tasks.connected_hfl import refresh_corpus_entities
    from core.apps.sprout.app.celery import SPROUT
    store, sent = queue
    with store.connection() as db:
        db.execute("INSERT INTO pending(id,revision,queued_at) VALUES ('waiting','v1',?)", (time.time(),))
    store.state('job', {'state': 'running', 'id': 'owner'})
    monkeypatch.setattr(refresh_corpus_entities, 'apply_async',
                        lambda **kwargs: pytest.fail('Duplicate created a retry chain'))
    with FileLock(str(store.path) + '.worker.lock'):
        for _ in range(20):
            assert refresh_corpus_entities.run(entry_id='waiting', revision='v1') == {'state': 'coalesced'}
    assert store.state('job') == {'state': 'running', 'id': 'owner'}
    with store.connection() as db:
        assert db.execute("SELECT revision FROM pending WHERE id='waiting'").fetchone()[0] == 'v1'
        # The existing ten-minute visibility timeout recovers even if the owner dies.
        db.execute("UPDATE pending SET queued_at=? WHERE id='waiting'", (time.time() - 601,))
    monkeypatch.setattr(entity_matching, 'dispatch_pending', lambda: None)
    monkeypatch.setattr(resolution, 'dispatch_pending', lambda: None)
    monkeypatch.setattr(SPROUT, 'send_task',
                        lambda *args, **kwargs: sent.append(kwargs) or SimpleNamespace(id='recovered'))
    assert entity_events.dispatch_pending()['state'] == 'queued'
    assert len(sent) == 1
    assert sent[0]['kwargs'] == {'entry_id': 'waiting', 'revision': 'v1'}
    assert entity_events.dispatch_pending()['state'] == 'pending'
    assert len(sent) == 1
