"""Beat schedule for repository-backed notes synchronization."""

from celery.schedules import crontab

from workflows.queues import WorkflowQueue


WORKFLOW_NOTES = {
    'run-job--broadcast_push_note_repositories': {
        'task': 'workflows.notes.tasks.sync_repositories.broadcast_push_note_repositories',
        'schedule': crontab(hour=22, minute=30),
        'kwargs': {},
        'options': {
            'queue': WorkflowQueue.DEFAULT_BROADCAST,
            'expires': 60 * 60,
        },
        'manifesto': {
            'code_role': 'organize',
            'para_bucket': 'area',
            'express_target': 'git_remote+es_log',
            'review_artifact': 'es_log',
            'hfl_signal': False,
        },
    },
    'run-job--pull_note_repositories': {
        'task': 'workflows.notes.tasks.sync_repositories.pull_note_repositories',
        'schedule': crontab(hour=22, minute=40),
        'kwargs': {},
        'options': {
            'queue': WorkflowQueue.HOST,
            'expires': 60 * 60,
        },
        'manifesto': {
            'code_role': 'organize',
            'para_bucket': 'area',
            'express_target': 'host_checkout+es_log',
            'review_artifact': 'es_log',
            'hfl_signal': False,
        },
    },
}
