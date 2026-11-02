"""No broker/model/live corpus: real file lock and temporary SQLite store."""
from concurrent.futures import ThreadPoolExecutor
from threading import Event
from types import SimpleNamespace
import sys

import pytest
from filelock import FileLock, Timeout

from workflows.hfl.entity_store import EntityStore
from workflows.knowledge.tasks.connected_hfl import refresh_corpus_entities as task


@pytest.fixture
def isolated(tmp_path, monkeypatch):
    monkeypatch.setenv('HARQIS_ENTITIES_QUEUE', 'test-entities')
    store = EntityStore(tmp_path / 'entities.sqlite3')
    monkeypatch.setattr('workflows.hfl.entity_store.get_store', lambda: store)
    monkeypatch.setitem(sys.modules, 'modules.hfl_corpus.entities', SimpleNamespace(
        enrich=lambda **kwargs: {'pending': 0, 'processed': 1}))
    monkeypatch.setattr('workflows.hfl.entity_matching.dispatch_pending', lambda: None)
    monkeypatch.setattr('workflows.hfl.entity_resolution.dispatch_pending', lambda: None)
    with store.connection() as db:
        db.execute('INSERT INTO pending VALUES (?,?,?)', ('entry', 'revision', 100))
    store.state('job', {'state': 'running', 'id': 'owner'})
    return store


def test_busy_worker_coalesces_without_exhausting_error_retries(isolated, monkeypatch):
    published = []
    monkeypatch.setattr(task, 'apply_async', lambda **kw: published.append(kw) or SimpleNamespace(id='deferred'))
    acquired, release = Event(), Event()
    def owner():
        with FileLock(str(isolated.path) + '.worker.lock', timeout=0):
            acquired.set()
            assert release.wait(10)
    with ThreadPoolExecutor(max_workers=1) as executor:
        future = executor.submit(owner)
        assert acquired.wait(5)
        task.push_request(id='contender', retries=4, called_directly=False)
        try:
            result = task.run(entry_id='entry', revision='revision', use_model=False)
        finally:
            task.pop_request()
            release.set()
            future.result()
    assert result == {'state': 'coalesced'}
    assert published == []
    assert isolated.state('job') == {'state': 'running', 'id': 'owner'}
    with isolated.connection() as db:
        assert db.execute('SELECT revision FROM pending').fetchone()[0] == 'revision'
        assert db.execute('SELECT COUNT(*) FROM enrichment_failures').fetchone()[0] == 0
    assert task.run(entry_id='entry', revision='revision', use_model=False)['processed'] == 1


def test_superseded_work_does_not_wait_for_busy_lock(isolated, monkeypatch):
    monkeypatch.setattr(task, 'apply_async', lambda **kw: pytest.fail('stale work published'))
    with FileLock(str(isolated.path) + '.worker.lock', timeout=0):
        assert task.run(entry_id='entry', revision='old') == {'state': 'superseded'}
    assert isolated.state('job') == {'state': 'running', 'id': 'owner'}


def test_legacy_handoff_preserves_retry_budget_in_real_celery_message(isolated):
    from celery import Celery
    app = Celery('contention-test', broker='memory://', backend='cache+memory://')
    local_task = app.task(bind=True, max_retries=4)(task.run.__func__)
    local_task.push_request(id='contender', retries=3, called_directly=False)
    try:
        with FileLock(str(isolated.path) + '.worker.lock', timeout=0):
            result = local_task.run(entry_id='entry', revision=None, use_model=False)
        with app.connection_for_read() as connection:
            with connection.SimpleQueue('test-entities') as queue:
                message = queue.get(block=False)
                assert message.headers['id'] == result['task_id']
                assert message.headers['retries'] == 3
                assert message.payload[1] == dict(entry_id='entry', revision=None, use_model=False)
                message.ack()
    finally:
        local_task.pop_request()
        app.close()


@pytest.mark.parametrize('error', [RuntimeError('provider unavailable'), Timeout('provider.lock')])
def test_provider_failure_still_exhausts_bounded_retries(isolated, monkeypatch, error):
    def fail(**kwargs):
        raise error
    monkeypatch.setattr(sys.modules['modules.hfl_corpus.entities'], 'enrich', fail)
    task.push_request(id='provider', retries=4, called_directly=False)
    try:
        with pytest.raises(RuntimeError) as raised:
            task.run(entry_id='entry', revision='revision')
        assert str(raised.value) == 'Entity enrichment failed: ' + type(error).__name__
    finally:
        task.pop_request()
    assert isolated.state('job')['state'] == 'quarantined'
    assert isolated.enrichment_status('entry', 'revision') == 'quarantined'
