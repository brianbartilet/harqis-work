"""Opt-in Beat schedule; one server worker owns the catalog and Drive publication."""
import os
from datetime import timedelta
from workflows.queues import qualify_queue

WORKFLOW_FILES = {}
if os.environ.get('FILES_ENABLED', '').lower() in {'1', 'true', 'yes'}:
    WORKFLOW_FILES['run-job--maintain-files'] = {
        'task': 'workflows.files.tasks.index.maintain_files',
        'schedule': timedelta(minutes=1),
        'options': {'queue': qualify_queue(os.environ.get('FILES_QUEUE', 'files')), 'expires': 55},
    }
