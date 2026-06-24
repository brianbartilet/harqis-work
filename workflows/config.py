"""
Configures the Celery app for scheduled tasks based on environment-specific settings.

This module initializes the Celery beat schedule using a configuration dictionary that maps task identifiers to their definitions. It dynamically selects the appropriate task mapping based on an environment variable, ensuring that tasks are scheduled according to environment-specific requirements. Additionally, it configures the Celery app to respect the timezone settings specified in the Django project settings, allowing for accurate scheduling of tasks across different timezones.

The configuration relies on external definitions for task mappings and environment variables to provide flexibility and modularity in defining task schedules.

References:
- Celery Periodic Tasks: https://docs.celeryproject.org/en/stable/userguide/periodic-tasks.html

Known Issues:
- Potential issues with Celery and Eventlet: https://github.com/eventlet/eventlet/issues/616
"""
from celery.signals import beat_init, worker_init
from kombu import Exchange, Queue
from kombu.common import Broadcast

from core.apps.sprout.app.celery import SPROUT
from core.apps.sprout.settings import TIME_ZONE, USE_TZ
from workflows.queues import WorkflowQueue

from workflows.purchases.tasks_config import WORKFLOW_PURCHASES
from workflows.hud.tasks_config import WORKFLOWS_HUD
from workflows.desktop.tasks_config import WORKFLOWS_DESKTOP
from workflows.social.tasks_config import WORKFLOW_SOCIAL
from workflows.knowledge.tasks_config import WORKFLOW_KNOWLEDGE
from workflows.dumps.tasks_config import WORKFLOW_DUMPS
from workflows.hfl.tasks_config import WORKFLOW_HFL
from workflows.workers.tasks_config import WORKFLOW_WORKERS
from workflows.testing.tasks_config import WORKFLOW_TESTING
from workflows.tcg.tasks_config import WORKFLOW_TCG

# Set Celery to use the same timezone settings as the Django project
SPROUT.conf.enable_utc = USE_TZ
SPROUT.conf.timezone = TIME_ZONE
SPROUT.conf.broker_connection_retry_on_startup = True
SPROUT.autodiscover_tasks(['workflows'])

# Configuration dictionary mapping environment variable values to specific task mappings.
# Be careful to use duplicate keys in the dictionary, as it will overwrite the previous key.
CONFIG_DICTIONARY = (
    WORKFLOW_PURCHASES
    | WORKFLOWS_HUD
    | WORKFLOWS_DESKTOP
    | WORKFLOW_SOCIAL
    | WORKFLOW_KNOWLEDGE
    | WORKFLOW_DUMPS
    | WORKFLOW_HFL
    | WORKFLOW_WORKERS
    | WORKFLOW_TESTING
    | WORKFLOW_TCG
)

# Celery's ScheduleEntry.__init__ only accepts these per-entry keys. Our
# tasks_config.py entries also carry a custom ``manifesto`` metadata block
# (code_role / para_bucket / … — consumed by registry/docs tooling, NOT by
# Celery). Handing the raw dict to Celery makes beat do
# ``ScheduleEntry(**entry)`` and die on startup with
# ``TypeError: ScheduleEntry.__init__() got an unexpected keyword argument
# 'manifesto'`` — every deploy, before it can log or write a pidfile.
# Whitelist the Celery-safe keys here so the metadata can stay in
# CONFIG_DICTIONARY for other consumers without ever reaching Celery.
_CELERY_ENTRY_KEYS = frozenset(
    {"task", "schedule", "args", "kwargs", "options", "relative"}
)


def _celery_safe_schedule(config: dict) -> dict:
    """Project each beat entry down to keys Celery's ScheduleEntry accepts."""
    return {
        name: {k: v for k, v in entry.items() if k in _CELERY_ENTRY_KEYS}
        for name, entry in config.items()
    }


# Configure the Celery beat schedule based on the current environment's task
# mapping. CONFIG_DICTIONARY keeps the full entries (incl. ``manifesto``);
# only the sanitized projection is handed to Celery.
SPROUT.conf.beat_schedule = _celery_safe_schedule(CONFIG_DICTIONARY)

# ── Queue topology ────────────────────────────────────────────────────────────
# Explicit declaration — Celery now creates exactly these queues on RabbitMQ at
# worker startup. Any new queue must be registered both here AND in
# `workflows.queues.WorkflowQueue`.
#
# Direct queues use the default (competing-consumers) exchange — one task is
# consumed by exactly one worker.
#
# Broadcast queues use a fanout exchange — RabbitMQ creates an anonymous
# auto-delete queue per consumer behind the scenes, so every subscribed worker
# receives every task. Tasks routed to a Broadcast queue MUST be idempotent —
# they run N times on N workers simultaneously.
SPROUT.conf.task_queues = (
    Queue(WorkflowQueue.DEFAULT.value),
    Queue(WorkflowQueue.HUD.value),
    Queue(WorkflowQueue.TCG.value),
    Queue(WorkflowQueue.ADHOC.value),
    Queue(WorkflowQueue.PEON.value),
    Queue(WorkflowQueue.N8N.value),
    Queue(WorkflowQueue.HFL.value),
    Broadcast(WorkflowQueue.DEFAULT_BROADCAST.value),
    Broadcast(WorkflowQueue.HUD_BROADCAST.value),
    Broadcast(WorkflowQueue.WORKERS_BROADCAST.value),
    Broadcast(WorkflowQueue.HFL_BROADCAST.value),
)
SPROUT.conf.task_default_queue = WorkflowQueue.DEFAULT.value

# Routing rules — more-specific patterns MUST come before catch-alls.
# Order matters: the first matching rule wins.
#
#   workflows.workers.tasks.broadcast_* → workers_broadcast (fanout)
#   workflows.hud.tasks.broadcast_*    → hud_broadcast     (fanout)
#   workflows.hud.tasks.*              → hud               (direct)
SPROUT.conf.task_routes = {
    "workflows.workers.tasks.broadcast_*": {"queue": WorkflowQueue.WORKERS_BROADCAST.value},
    "workflows.hud.tasks.broadcast_*":     {"queue": WorkflowQueue.HUD_BROADCAST.value},
    # Data-only fallback twins run on the always-on host, NOT the Windows hud
    # queue. This more-specific rule MUST precede the hud catch-all below
    # (first match wins) or the twins would be routed to `hud` and never run
    # when Windows is offline — defeating their purpose.
    "workflows.hud.tasks.hud_data_only.*": {"queue": WorkflowQueue.HOST.value},
    "workflows.hud.tasks.*":               {"queue": WorkflowQueue.HUD.value},
}


# ── Broadcast exchange pre-declaration ────────────────────────────────────────
# Kombu's Broadcast(...) creates the fanout exchange ON THE CONSUMER SIDE — i.e.
# only when a worker subscribes. If Beat publishes before any worker has
# subscribed (or while the worker is restarting), RabbitMQ returns 404
# NOT_FOUND, the AMQP channel dies, and EVERY subsequent publish in the same
# tick fails — even unrelated direct-queue tasks like `show_mouse_bindings`,
# because they reuse the poisoned channel. Declaring the fanout exchanges on
# Beat (and worker) startup avoids that cascade.
_BROADCAST_QUEUES = (
    WorkflowQueue.DEFAULT_BROADCAST.value,
    WorkflowQueue.HUD_BROADCAST.value,
    WorkflowQueue.WORKERS_BROADCAST.value,
    WorkflowQueue.AGENT_BROADCAST.value,
    WorkflowQueue.HFL_BROADCAST.value,
)


def _ensure_broadcast_exchanges(app):
    with app.connection_or_acquire() as conn:
        channel = conn.default_channel
        for name in _BROADCAST_QUEUES:
            Exchange(name, type='fanout', durable=True)(channel).declare()


@beat_init.connect
def _declare_on_beat(sender=None, **_):
    _ensure_broadcast_exchanges(sender.app)


@worker_init.connect
def _declare_on_worker(sender=None, **_):
    _ensure_broadcast_exchanges(sender.app)


# ── HFL auto-express (Option B / Phase 1) ─────────────────────────────────────
# Connect the task_success → HFL signal-buffer handler. Imported HERE, at the
# bottom of the module, for two reasons:
#   1. The handler recovers each task's `manifesto` block from CONFIG_DICTIONARY
#      (defined above) at runtime — the block is stripped from the Celery
#      schedule by _celery_safe_schedule, so this is the only place it survives.
#   2. workflows.config is the module the sprout app imports on BOTH beat and
#      worker startup (core/apps/sprout/__init__.py), so importing the handler
#      here guarantees the signal connects in both processes.
# express_signals imports CONFIG_DICTIONARY lazily, so this import is not
# circular. See docs/thesis/HFL-AUTO-EXPRESS.md.
import workflows.hfl.express_signals  # noqa: E402,F401
