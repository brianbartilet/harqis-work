"""Durable enrichment intent after canonical writes; producers never wait for models."""
import logging
import os
import uuid
import time
from workflows.hfl.entity_store import get_store

log = logging.getLogger(__name__)
TASK = 'workflows.knowledge.tasks.connected_hfl.refresh_corpus_entities'


def request_enrichment(entry_id='*'):
    if not os.environ.get('HARQIS_ENTITIES_DB'):
        return {'state': 'disabled'}
    store = get_store()
    with store.connection() as db:
        db.execute('INSERT OR REPLACE INTO pending(id,revision) VALUES (?,?)', (entry_id, uuid.uuid4().hex))
    return dispatch_pending()


def dispatch_pending():
    if not os.environ.get('HARQIS_ENTITIES_DB'):
        return {'state': 'disabled'}
    from core.apps.sprout.app.celery import SPROUT
    store = get_store()
    with store.connection() as db:
        pending = list(db.execute('SELECT * FROM pending WHERE queued_at < ? LIMIT 20', (time.time()-600,)))
    ids = []
    for row in pending:
        try:
            result = SPROUT.send_task(TASK, kwargs={'entry_id': row['id'], 'revision': row['revision']},
                                     queue=os.environ.get('HARQIS_ENTITIES_QUEUE', 'hfl'))
            ids.append(str(result.id))
            with store.connection() as db:
                db.execute('UPDATE pending SET queued_at=? WHERE id=? AND revision=?',
                           (time.time(), row['id'], row['revision']))
        except Exception as exc:
            log.warning('Entity work remains pending: %s', type(exc).__name__)
            break
    return {'state': 'queued' if ids else 'pending', 'task_ids': ids}


def notify_change(entry_id='*'):
    try:
        return request_enrichment(entry_id)
    except Exception as exc:
        log.error('Entity enrichment notification failed: %s', type(exc).__name__)
        return {'state': 'failed', 'error': type(exc).__name__}
