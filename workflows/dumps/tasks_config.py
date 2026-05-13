"""
Beat schedule for the `dumps` workflow.

Three entries:
  - broadcast_collect_daily_dumps : fanout to every default_broadcast worker;
                                    each ships its own paths to harqis-server.
  - pull_daily_dumps_from_remotes : runs on harqis-server only; pulls from
                                    Android (Termux SSHD) and other non-celery
                                    devices listed under [dumps.pull_targets].
  - analyze_daily_dumps           : placeholder — logs file counts. The agent
                                    wire-up is marked AGENT WIRE-UP HERE in
                                    workflows/dumps/tasks/analyze.py.

All three fire once a day. Beat runs on harqis-server only (canonical Beat
runner per machines.toml — every other host has scheduler disabled).

`expires`: 8 hours. If a worker doesn't pick up the broadcast within that
window (machine offline, RabbitMQ outage, etc.), the task is dropped to
avoid a backlog colliding with the next day's run.
"""
from celery.schedules import crontab
from workflows.queues import WorkflowQueue


WORKFLOW_DUMPS = {

    # ── 00:00 every day — every celery worker on default_broadcast collects ─
    'run-job--broadcast_collect_daily_dumps': {
        'task': 'workflows.dumps.tasks.broadcast_collect_daily_dumps',
        'schedule': crontab(hour=0, minute=0),
        'options': {
            'queue': WorkflowQueue.DEFAULT_BROADCAST,
            'expires': 60 * 60 * 8,
        },
        'manifesto': {
            'code_role': 'capture',
            'para_bucket': 'area',
            'express_target': 'file:dump_inbox',
            'review_artifact': 'es_log',
            'hfl_signal': True,
        },
    },

    # ── 00:05 every day — harqis-server pulls from Android et al. ───────────
    # Staggered 5 min after the broadcast so most pushes have landed first.
    'run-job--pull_daily_dumps_from_remotes': {
        'task': 'workflows.dumps.tasks.pull_daily_dumps_from_remotes',
        'schedule': crontab(hour=0, minute=5),
        'options': {
            'queue': WorkflowQueue.HOST,
            'os': ['windows', 'macos', 'linux'],
            'expires': 60 * 60 * 8,
        },
        'manifesto': {
            'code_role': 'capture',
            'para_bucket': 'area',
            'express_target': 'file:dump_inbox',
            'review_artifact': 'es_log',
            'hfl_signal': True,
        },
    },

    # ── 01:00 every day — inbox analyzer + HUD summary tile ─────────────────
    # Runs an hour after collection completes. Walks the day's inbox, then
    # pushes a per-machine summary line to the HUD feed (closes the manifesto
    # dead-weight gap — see docs/thesis/MANIFESTO-REPO-UPDATES.md §4.5).
    # Trello hand-off remains a future follow-up; the marker stays in code.
    'run-job--analyze_daily_dumps': {
        'task': 'workflows.dumps.tasks.analyze_daily_dumps',
        'schedule': crontab(hour=1, minute=0),
        'options': {
            'queue': WorkflowQueue.HOST,
            'os': ['windows', 'macos', 'linux'],
            'expires': 60 * 60 * 8,
        },
        'manifesto': {
            'code_role': 'distill+express',
            'para_bucket': 'area',
            'express_target': 'hud_feed',
            'review_artifact': 'es_log+hud_feed',
            'hfl_signal': True,
        },
    },

}
