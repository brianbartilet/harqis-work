"""Offline durable retry budget: fake provider/broker, real temporary SQLite."""
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace

import pytest

from modules.hfl_corpus import entities
from workflows.hfl import entity_events
from workflows.hfl.entity_store import EntityStore, get_store
from workflows.knowledge.tasks.connected_hfl import refresh_corpus_entities as task


@pytest.fixture
def work(monkeypatch):
    from core.apps.sprout.app.celery import SPROUT
    monkeypatch.setattr('workflows.hfl.entity_matching.dispatch_pending', lambda: None)
    monkeypatch.setattr('workflows.hfl.entity_resolution.dispatch_pending', lambda: None)
    sent = []
    monkeypatch.setattr(SPROUT, 'send_task', lambda *a, **kw: sent.append(kw) or SimpleNamespace(id='sent'))
    monkeypatch.setattr(task, 'apply_async', lambda **kw: SimpleNamespace(id='child'))
    monkeypatch.setattr(entities, 'enrich', lambda **kw: {'pending': 1, 'processed': 0})
    def retry(**kw):
        raise kw['exc']
    monkeypatch.setattr(task, 'retry', retry)
    entity_events.request_enrichment('one')
    return get_store(), sent


def pending(store):
    with store.connection() as db:
        return dict(db.execute('SELECT * FROM pending WHERE id="one"').fetchone())


def run_failure(revision, retries=0):
    task.push_request(id='offline', retries=retries, called_directly=False)
    try:
        with pytest.raises(RuntimeError):
            task.run(entry_id='one', revision=revision)
    finally:
        task.pop_request()


def test_budget_survives_fresh_task_retry_counters_and_store_reopens(work):
    store, sent = work
    revision = pending(store)['revision']
    for _ in range(5):
        run_failure(revision)
        store = EntityStore(store.path)
        with store.connection() as db:
            db.execute('UPDATE pending SET queued_at=0')
        entity_events.dispatch_pending()
    assert len(sent) == 5  # Initial send plus four redispatches, never a sixth.
    assert task.run(entry_id='one', revision=revision) == {'state': 'quarantined'}
    with store.connection() as db:
        row = db.execute('SELECT * FROM enrichment_failures').fetchone()
    assert row['failures'] == 5 and row['state'] == 'quarantined'
    assert store.records() == {}


def test_exhausted_task_quarantines_and_new_revision_recovers(work, monkeypatch):
    store, sent = work
    old = pending(store)['revision']
    run_failure(old, retries=4)
    with store.connection() as db:
        db.execute('UPDATE pending SET queued_at=0')
    assert entity_events.dispatch_pending()['task_ids'] == []
    entity_events.request_enrichment('one')
    new = pending(store)['revision']
    assert new != old
    assert task.run(entry_id='one', revision=old) == {'state': 'superseded'}
    monkeypatch.setattr(entities, 'enrich', lambda **kw: {'pending': 0, 'processed': 1})
    assert task.run(entry_id='one', revision=new)['processed'] == 1
    with store.connection() as db:
        assert db.execute('SELECT COUNT(*) FROM pending').fetchone()[0] == 0
        assert db.execute('SELECT COUNT(*) FROM enrichment_failures').fetchone()[0] == 0


def test_failure_from_old_inflight_revision_cannot_poison_new(work, monkeypatch):
    store, sent = work
    old = pending(store)['revision']
    def changed(**kw):
        entity_events.request_enrichment('one')
        raise RuntimeError('PRIVATE PROVIDER TEXT')
    monkeypatch.setattr(entities, 'enrich', changed)
    task.push_request(id='stale', retries=4, called_directly=False)
    try:
        assert task.run(entry_id='one', revision=old) == {'state': 'superseded'}
    finally:
        task.pop_request()
    assert pending(store)['revision'] != old
    with store.connection() as db:
        assert db.execute('SELECT COUNT(*) FROM enrichment_failures').fetchone()[0] == 0


def test_old_success_cannot_delete_replacement_intent(work, monkeypatch):
    store, _ = work
    old = pending(store)['revision']
    def changed(**kw):
        entity_events.request_enrichment('one')
        return {'pending': 0, 'processed': 1}
    monkeypatch.setattr(entities, 'enrich', changed)
    assert task.run(entry_id='one', revision=old) == {'state': 'superseded'}
    assert pending(store)['revision'] != old


def test_failure_messages_are_sanitized(work, monkeypatch):
    store, _ = work
    def fail(**kw):
        raise RuntimeError('PRIVATE PROVIDER TEXT')
    monkeypatch.setattr(entities, 'enrich', fail)
    with pytest.raises(RuntimeError) as error:
        task.run(entry_id='one', revision=pending(store)['revision'])
    assert 'PRIVATE' not in str(error.value)
    assert error.value.__suppress_context__
    assert 'PRIVATE' not in str(store.state('job'))


def test_concurrent_failure_accounting_and_terminal_state_are_atomic(work):
    store, _ = work
    revision = pending(store)['revision']
    with ThreadPoolExecutor(max_workers=4) as pool:
        list(pool.map(lambda _: store.fail_enrichment('one', revision, RuntimeError()), range(4)))
    with store.connection() as db:
        assert db.execute('SELECT failures FROM enrichment_failures').fetchone()[0] == 4
    assert store.fail_enrichment('one', revision, RuntimeError()) == 'quarantined'


def test_exhausted_quarantine_cannot_be_reopened_by_late_failure(work):
    store, _ = work
    revision = pending(store)['revision']
    assert store.fail_enrichment('one', revision, RuntimeError(), exhausted=True) == 'quarantined'
    assert store.fail_enrichment('one', revision, RuntimeError()) == 'quarantined'


def test_legacy_pending_schema_gains_budget_without_losing_intent(tmp_path):
    path = tmp_path / 'legacy.sqlite3'
    with sqlite3.connect(path) as db:
        db.execute('CREATE TABLE pending(id TEXT PRIMARY KEY, revision TEXT, queued_at REAL DEFAULT 0)')
        db.execute('INSERT INTO pending VALUES ("one","old",0)')
    EntityStore(path)
    with ThreadPoolExecutor(max_workers=4) as pool:
        stores = list(pool.map(lambda _: EntityStore(path), range(8)))
    assert pending(stores[0])['revision'] == 'old'
    with stores[0].connection() as db:
        assert db.execute('SELECT COUNT(*) FROM enrichment_failures').fetchone()[0] == 0
