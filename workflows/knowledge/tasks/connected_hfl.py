"""Corpus-derived enrichment: fixed schema, bounded batches, Celery-owned retries."""
import os
import sys
import time
from pathlib import Path
from filelock import FileLock, Timeout
from core.apps.sprout.app.celery import SPROUT

@SPROUT.task(bind=True, acks_late=True, reject_on_worker_lost=True, max_retries=4)
def refresh_corpus_entities(self, entry_id='*', revision=None, use_model=True):
    frontend = str(Path(__file__).resolve().parents[3] / 'frontend')
    if frontend not in sys.path:
        sys.path.insert(0, frontend)
    from workflows.hfl.entity_store import get_store
    from modules.hfl_corpus.entities import enrich
    store = get_store()
    try:
        # Cheap stale-message rejection must not wait behind a long model batch.
        # Recheck after acquisition below to cover concurrent canonical writes.
        if revision:
            with store.connection() as db:
                row = db.execute('SELECT revision FROM pending WHERE id=?', (entry_id,)).fetchone()
                if not row or row['revision'] != revision:
                    return {'state': 'superseded'}
        lock = FileLock(str(store.path) + '.worker.lock', timeout=0)
        try:
            lock.acquire()
        except Timeout:
            if revision:
                # The pending row is durable and the owner or outbox dispatcher
                # will continue it. Broker duplicates must not own retry chains.
                return {'state': 'coalesced'}
            # Another pool thread/process is doing valid work. Hand off without
            # spending the provider-error retry budget or overwriting its state.
            # Legacy direct calls have no durable revision for outbox recovery.
            child = self.apply_async(
                kwargs=dict(entry_id=entry_id, revision=revision, use_model=use_model),
                queue=os.environ.get('HARQIS_ENTITIES_QUEUE', 'hfl'), countdown=30,
                retries=self.request.retries)
            return {'state': 'deferred', 'task_id': str(child.id)}
        try:
            if revision:
                with store.connection() as db:
                    row = db.execute('SELECT revision FROM pending WHERE id=?', (entry_id,)).fetchone()
                    if not row or row['revision'] != revision:
                        return {'state': 'superseded'}
                    db.execute('UPDATE pending SET queued_at=? WHERE id=?', (time.time(), entry_id))
            store.state('job', {'state': 'running', 'id': self.request.id})
            result = enrich(entry_id=None if entry_id == '*' else entry_id, use_model=use_model)
            from workflows.hfl.entity_resolution import dispatch_pending as dispatch_resolutions
            dispatch_resolutions()
            from workflows.hfl.entity_matching import dispatch_pending
            dispatch_pending()
            if result['pending'] and result['processed']:
                child = self.apply_async(kwargs=dict(entry_id=entry_id, revision=revision, use_model=use_model),
                                        queue=os.environ.get('HARQIS_ENTITIES_QUEUE', 'hfl'), countdown=2)
                store.state('job', {'state': 'queued', 'id': str(child.id), 'result': result})
            elif result['pending']:
                raise RuntimeError('Provider returned no usable results; pending work retained')
            else:
                with store.connection() as db:
                    db.execute('DELETE FROM pending WHERE id=? AND revision=?', (entry_id, revision))
                store.state('job', {'state': 'complete', 'id': self.request.id, 'result': result})
            return result
        finally:
            lock.release()
    except Exception as exc:
        store.state('job', {'state': 'retrying' if self.request.retries < 4 else 'failed',
                            'error': type(exc).__name__, 'id': self.request.id})
        raise self.retry(exc=exc, countdown=min(300, 15 * 2 ** self.request.retries))


@SPROUT.task(bind=True, acks_late=True, reject_on_worker_lost=True, max_retries=4)
def match_corpus_entities(self, job_id):
    frontend = str(Path(__file__).resolve().parents[3] / 'frontend')
    if frontend not in sys.path:
        sys.path.insert(0, frontend)
    from workflows.hfl.entity_matching import enabled, process_batch
    from workflows.hfl.entity_store import get_store
    if not enabled():
        return {'state':'disabled'}
    store = get_store()
    try:
        with FileLock(str(store.path) + '.matching.lock', timeout=0):
            result = process_batch(job_id)
            if result['pending']:
                self.apply_async(kwargs={'job_id':job_id}, queue=os.environ.get('HARQIS_ENTITIES_QUEUE','hfl'), countdown=2)
            return result
    except Exception as exc:
        with store.connection() as db:
            db.execute('UPDATE entity_match_jobs SET error=?,state=CASE WHEN ? THEN ? ELSE state END WHERE id=?',
                       (type(exc).__name__, self.request.retries >= 4, 'failed', job_id))
        raise self.retry(exc=exc, countdown=min(300, 15 * 2 ** self.request.retries))


@SPROUT.task(bind=True, acks_late=True, reject_on_worker_lost=True, max_retries=4)
def resolve_corpus_entities(self, dispatch_id=None):
    frontend = str(Path(__file__).resolve().parents[3] / 'frontend')
    if frontend not in sys.path:
        sys.path.insert(0, frontend)
    from workflows.hfl.entity_resolution import process_pending, dispatch_pending
    from workflows.hfl.entity_store import get_store
    store = get_store()
    lock = FileLock(str(store.path) + '.resolution.lock', timeout=0)
    try:
        lock.acquire()
    except Timeout:
        # The owner schedules continuation; duplicate deliveries must not create
        # independent retry chains. Durable intent survives an owner crash.
        return {'state': 'coalesced'}
    try:
        reservation = store.state('resolution-wakeup') or {}
        if (dispatch_id and dispatch_id != reservation.get('token')) or (not dispatch_id and reservation):
            return {'state': 'superseded'}
        store.state('resolution-wakeup', {})
        try:
            result = process_pending()
            store.state('resolution-task-error', {})
        except Exception as exc:
            now = time.time()
            store.state('resolution-task-error', dict(at=now, error=type(exc).__name__, retry_at=now + 60))
            # Never persist provider messages or source payloads in Celery errors.
            raise RuntimeError('Entity resolution batch failed: ' + type(exc).__name__) from None
    finally:
        lock.release()
        dispatch_pending()
    if result.get('errors'):
        # Entry retries and continuation are already durable. Raising here makes
        # Celery FAILURE truthful without replaying successful entries.
        raise RuntimeError('Entity resolution partial failure: '
                           + str(len(result['errors'])) + ' entries failed; '
                           + str(result['processed']) + ' processed; inspect resolution status')
    return result
