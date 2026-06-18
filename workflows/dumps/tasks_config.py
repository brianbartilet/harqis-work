"""
Beat schedule for the `dumps` workflow.

Entries:
  - broadcast_collect_daily_dumps : fanout to every default_broadcast worker;
                                    each ships its own paths to harqis-server.
  - broadcast_collect_today_dumps : intra-day catch-up (every 4h) — same task,
                                    include_today=True for same-day edits.
  - pull_daily_dumps_from_remotes : runs on harqis-server only; pulls from
                                    Android (Termux SSHD) and other non-celery
                                    devices listed under [dumps.pull_targets].
  - analyze_daily_dumps           : walks yesterday's inbox, pushes a per-machine
                                    summary to the HUD feed. Self-guards to
                                    harqis-server (workflows/dumps/tasks/analyze.py).
  - analyze_dumps_weekly_catchup  : Mon 01:30 retro — same task with days=7, to
                                    surface any missed daily runs.

Beat runs on harqis-server only (canonical Beat runner per machines.toml —
every other host has scheduler disabled).

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

    # ── Intra-day catch-up — every 4h during the working day, ships TODAY's ─
    # edits without waiting for the next 00:00 batch. Same broadcast task, but
    # `include_today=True` widens the window to [today 00:00, now] so same-day
    # changes (and a missed midnight run) propagate to the host the same day.
    # Files land in a `<machine>-daily-dumps-<today>` folder; each run re-ships
    # the day's growing set (overwrites), so keep dump paths scoped. Tune the
    # cadence here if 4h is too coarse/frequent.
    'run-job--broadcast_collect_today_dumps': {
        'task': 'workflows.dumps.tasks.broadcast_collect_daily_dumps',
        'schedule': crontab(hour='8,12,16,20', minute=30),
        'kwargs': {
            'window_days': 1,
            'include_today': True,
        },
        'options': {
            'queue': WorkflowQueue.DEFAULT_BROADCAST,
            'expires': 60 * 60 * 4,
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

    # ── Mon 01:30 — weekly catch-up: re-summarize the trailing 7 days ────────
    # The daily run only ever sees yesterday, so a missed daily run (host
    # offline, broker outage, the host-queue race we fixed) leaves a permanent
    # gap. This retro pass walks the last 7 days and emits a per-day breakdown
    # to the HUD feed, surfacing any "0 machines (no dumps)" days so they're
    # visible instead of silently lost. Idempotent — re-reading existing dump
    # folders, writing only a feed summary. For ad-hoc ranges (a whole month,
    # a specific day) run scripts/agents/dumps/run_dumps_summary_retro.py on harqis-server.
    'run-job--analyze_dumps_weekly_catchup': {
        'task': 'workflows.dumps.tasks.analyze_daily_dumps',
        'schedule': crontab(hour=1, minute=30, day_of_week=1),
        'kwargs': {'days': 7},
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
