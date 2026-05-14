# workflows/workers — cluster-wide worker telemetry broadcasts.
#
# Tasks in this package run on every subscribed Celery worker via the
# `workers_broadcast` fanout queue.  Each task MUST be idempotent — it
# executes on every worker simultaneously, so no shared file writes or
# "exactly-once" side-effects.
#
# Queue: WorkflowQueue.WORKERS_BROADCAST (fanout / Broadcast)
# Route: "workflows.workers.tasks.broadcast_*" → workers_broadcast
#
# Current tasks:
#   broadcast_report_location — every worker reports its GPS coordinates
#                               to Elasticsearch (harqis-worker-locations).
