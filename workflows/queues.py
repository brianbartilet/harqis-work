from enum import StrEnum


class WorkflowQueue(StrEnum):
    """Logical queues consumed by Celery workers.

    Each value is the literal queue name Celery / RabbitMQ uses on the wire.
    See `workflows.config` for queue declarations (direct vs fanout).
    """

    # ── Direct (competing-consumers) queues — exactly one worker handles each task ──
    DEFAULT = "default"
    HUD = "hud"
    TCG = "tcg"
    ADHOC = "adhoc"
    PEON = "peon"   # work-related HUD tasks (Jira boards, calendar focus, etc.)
    AGENTS = "agents"

    # ── Broadcast (fanout) queues — every subscribed worker handles each task ──
    # Use for cluster-wide actions: config reload, cache invalidation, "every HUD
    # node refresh now". Tasks routed here MUST be idempotent — they run on every
    # worker that subscribes (typically several at once).
    HUD_BROADCAST = "hud_broadcast"
