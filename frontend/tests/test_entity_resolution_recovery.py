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
    (json.dumps({'decisions': [decision(), decision()]}), 'end_turn', 'unexpected-or-duplicate-id'),
    (json.dumps({'decisions': [decision('unknown')]}), 'end_turn', 'unexpected-or-duplicate-id'),
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


def test_response_error_survives_celery_exception_serialization():
    import pickle
    error = EntityModelResponseError({'reason': 'truncated', 'stop_reason': 'max_tokens'})
    restored = pickle.loads(pickle.dumps(error))
    assert restored.diagnostics == error.diagnostics
    assert str(restored) == str(error)
