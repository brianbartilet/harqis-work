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
from workflows.projects.tasks_config import WORKFLOW_PROJECTS

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
    | WORKFLOW_PROJECTS
)

# Configure the Celery beat schedule based on the current environment's task mapping.
SPROUT.conf.beat_schedule = CONFIG_DICTIONARY

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
    Broadcast(WorkflowQueue.DEFAULT_BROADCAST.value),
    Broadcast(WorkflowQueue.HUD_BROADCAST.value),
)
SPROUT.conf.task_default_queue = WorkflowQueue.DEFAULT.value

# Routing rules — tasks named `workflows.hud.tasks.broadcast_*` go to the
# fanout queue and run on every subscribed worker. Everything else under
# `workflows.hud.tasks.*` keeps the existing single-worker behaviour.
# Order matters: more-specific patterns first.
SPROUT.conf.task_routes = {
    "workflows.hud.tasks.broadcast_*": {"queue": WorkflowQueue.HUD_BROADCAST.value},
    "workflows.hud.tasks.*":           {"queue": WorkflowQueue.HUD.value},
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