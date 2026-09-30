"""Host-affine file jobs. The catalog's audit log is the Review artifact."""
import os
import time

from core.apps.sprout.app.celery import SPROUT
from apps.file_index.service import expire, publish, scan
from apps.file_index.store import Store
from workflows.queues import qualify_queue


@SPROUT.task(autoretry_for=(OSError, RuntimeError), retry_backoff=30, retry_backoff_max=600,
             retry_jitter=True, max_retries=3, acks_late=True, soft_time_limit=3500, time_limit=3600)
def scan_source(source_id):
    return scan(source_id)


@SPROUT.task(autoretry_for=(Exception,), retry_backoff=30, retry_backoff_max=600,
             retry_jitter=True, max_retries=3, acks_late=True, soft_time_limit=3500, time_limit=3600)
def publish_package(revision_id):
    return publish(revision_id)


@SPROUT.task(soft_time_limit=110, time_limit=120)
def maintain_files():
    store = Store()
    with store.lease('maintenance', seconds=180):
        results = expire(store)
        queued = []
        for source in store.all('sources'):
            if not source.get('enabled') or source['kind'] == 'ftp':
                continue
            last = max(source.get('last_scan') or 0, source.get('last_queued') or 0)
            if time.time() - last >= source['interval_hours'] * 3600:
                task = scan_source.apply_async(kwargs={'source_id': source['id']}, queue=qualify_queue(os.environ.get('FILES_QUEUE', 'files')))
                store.patch('sources', source['id'], {'last_queued': time.time()})
                store.event(source['id'], 'scan_scheduled', task_id=task.id)
                queued.append(task.id)
        return {**results, 'queued': queued}
