"""Celery Beat reconciliation for the Thinking Second Brain data plane."""

from datetime import timedelta

from workflows.queues import WorkflowQueue


WORKFLOW_SECOND_BRAIN = {
    "run-job--reconcile_second_brain": {
        "task": "workflows.second_brain.tasks.reconcile.reconcile_second_brain",
        "schedule": timedelta(minutes=15),
        "kwargs": {},
        "options": {
            "queue": WorkflowQueue.HOST,
            "expires": 12 * 60,
        },
        "manifesto": {
            "code_role": "capture+organize+distill+express",
            "para_bucket": "area",
            "express_target": "api:second-brain-feed",
            "review_artifact": "es_log+second_brain_store",
            "hfl_signal": True,
        },
    },
}
