"""
Beat schedule for the ``workers`` workflow.

Entry
-----
``broadcast_report_location`` fans out to every Celery worker subscribed to
the ``workers_broadcast`` queue.  Each worker independently resolves its own
location (env vars → IP-geo → OwnTracks) and writes one document to the
``harqis-worker-locations`` Elasticsearch index.

Schedule
--------
Every 5 minutes — frequent enough for a live fleet dashboard in Kibana
while keeping ES ingest and ip-api.com load minimal.  Adjust via the
``timedelta`` below if a different cadence is needed per-environment.

``expires``
-----------
300 seconds (5 minutes) — matches the cadence so a missed tick is simply
dropped rather than queued behind the next one.  Workers that are offline
when the broadcast fires will not catch up; the gap in ES is intentional
(it shows the worker was unreachable).

Fanout semantics
----------------
Tasks routed to ``workers_broadcast`` run on *every* subscribed worker
simultaneously.  Make sure the body remains idempotent — no shared file
writes, no "exactly-once" side-effects.  Each worker writes to its own
``<machine_name>_latest`` document ID so concurrent execution across
machines is safe.

To subscribe a new worker to location broadcasts, add ``workers_broadcast``
to its ``-Q`` queue list:

    python scripts/deploy.py --role node -q default,workers_broadcast
"""
from datetime import timedelta
from workflows.queues import WorkflowQueue

WORKFLOW_WORKERS = {

    # ── Every 5 minutes — every worker on workers_broadcast reports location ─
    "run-job--broadcast_report_location": {
        "task": "workflows.workers.tasks.broadcast_report_location",
        "schedule": timedelta(minutes=5),
        "kwargs": {
            # Override if OWN_TRACKS is configured under a different key in
            # apps_config.yaml (e.g. "OWN_TRACKS_HOME" vs "OWN_TRACKS_WORK").
            "owntracks_cfg_id": "OWN_TRACKS",
        },
        "options": {
            "queue":   WorkflowQueue.WORKERS_BROADCAST,
            "expires": 60 * 5,   # drop if not consumed within one cadence
        },
    },

}
