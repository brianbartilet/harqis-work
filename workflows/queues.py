import os
import re
from enum import StrEnum


def instance_slug() -> str:
    """Return the optional namespace used to isolate this HARQIS instance."""
    raw = os.environ.get("HARQIS_QUEUE_PREFIX") or os.environ.get(
        "HARQIS_INSTANCE", ""
    )
    return re.sub(r"[^a-z0-9]+", "-", raw.lower()).strip("-")


def qualify_queue(queue: str) -> str:
    """Prefix a queue for this instance while preserving upstream compatibility."""
    queue = queue.strip()
    prefix = instance_slug()
    if not prefix or queue.startswith(f"{prefix}."):
        return queue
    return f"{prefix}.{queue}"


def qualify_queues(queues: str) -> str:
    """Qualify a comma-separated worker queue list."""
    return ",".join(qualify_queue(queue) for queue in queues.split(",") if queue.strip())


class WorkflowQueue(StrEnum):
    """Logical queues consumed by Celery workers.

    Each value is the literal queue name Celery / RabbitMQ uses on the wire.
    See `workflows.config` for queue declarations (direct vs fanout).
    """

    # ── Direct (competing-consumers) queues — exactly one worker handles each task ──
    DEFAULT = qualify_queue("default")
    HOST = qualify_queue("host")
    HUD = qualify_queue("hud")
    TCG = qualify_queue("tcg")
    ADHOC = qualify_queue("adhoc")
    PEON = qualify_queue("peon")   # work-related HUD tasks (Jira boards, calendar focus, etc.)
    AGENT = qualify_queue("agent")
    WORKER = qualify_queue("worker")
    N8N = qualify_queue("n8n")     # n8n container ops (backup/restore/deploy) — pinned to harqis-server
    HFL = qualify_queue("hfl")     # Homework-for-Life: capture/ingest/summarize/recall — harqis-server
    CAPTURE = qualify_queue("capture")  # isolated Windows desktop screen-reader supervisor

    # ── Broadcast (fanout) queues — every subscribed worker handles each task ──
    # Use for cluster-wide actions: config reload, cache invalidation, "every HUD
    # node refresh now". Tasks routed here MUST be idempotent — they run on every
    # worker that subscribes (typically several at once).
    DEFAULT_BROADCAST = qualify_queue("default_broadcast")
    HUD_BROADCAST = qualify_queue("hud_broadcast")
    WORKERS_BROADCAST = qualify_queue("workers_broadcast")
    AGENT_BROADCAST = qualify_queue("agents_broadcast")
    HFL_BROADCAST = qualify_queue("hfl_broadcast")   # HFL ingest tasks fanned out to every worker
                                      # (each captures its own local signal)
