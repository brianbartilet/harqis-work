"""Weekly schedule for read-only fork drift/readiness analysis and HFL reporting."""

from celery.schedules import crontab

from workflows.queues import WorkflowQueue


WORKFLOW_GIT_FORKS = {
    # Weekly Sunday scan, early enough to inform the existing Sunday HFL rollups.
    "run-job--scan_fork_fleet": {
        "task": "workflows.git_forks.tasks.scan_forks.scan_fork_fleet",
        "schedule": crontab(day_of_week="sun", hour=6, minute=0),
        "args": [],
        "options": {
            "queue": WorkflowQueue.HOST,
            "expires": 60 * 60 * 23,
        },
        "manifesto": {
            "code_role": "capture+organize+distill+express",
            "para_bucket": "area",
            "express_target": "file:fork_fleet_report+hfl_corpus",
            "review_artifact": "es_log+file",
            "hfl_signal": True,
        },
    },
}
