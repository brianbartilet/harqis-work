"""Routing + topology tests for the hud_broadcast fanout queue.

These tests don't talk to RabbitMQ — they only assert that the Celery app's
declared topology says what we expect. If they fail, no message has actually
been mis-routed yet; a config drift was caught early.
"""
from __future__ import annotations

import os

import pytest
from hamcrest import assert_that, equal_to, contains_string, has_item, instance_of

# Make sure SPROUT loads `workflows.config` (which is what registers
# task_queues + task_routes) before we read the conf.
os.environ.setdefault("WORKFLOW_CONFIG", "workflows.config")
os.environ.setdefault("APP_CONFIG_FILE", "apps_config.yaml")

from kombu import Queue  # noqa: E402
from kombu.common import Broadcast  # noqa: E402

from core.apps.sprout.app.celery import SPROUT  # noqa: E402

# Importing workflows.config registers the queues + routes onto SPROUT.conf.
import workflows.config  # noqa: F401, E402

from workflows.queues import WorkflowQueue  # noqa: E402


def _stable_name(q) -> str:
    """Stable identifier for a declared queue.

    For a regular `Queue`, the queue name itself is stable.
    For a `Broadcast`, `Broadcast.name` is an auto-generated per-instance UUID
    (because RabbitMQ auto-creates an anonymous queue per consumer behind the
    scenes); the stable identifier is the fanout exchange's name, which is what
    `task_routes` uses to route messages.
    """
    if isinstance(q, Broadcast):
        return q.exchange.name
    return q.name


def _queue_named(name: str):
    """Find a declared queue (Queue or Broadcast) by stable name."""
    for q in SPROUT.conf.task_queues or ():
        if _stable_name(q) == name:
            return q
    return None


# ── Topology ─────────────────────────────────────────────────────────────────

@pytest.mark.smoke
def test_all_known_queues_are_declared():
    """Every WorkflowQueue value must appear in SPROUT.conf.task_queues —
    otherwise Celery silently routes to a non-existent queue."""
    declared_names = {_stable_name(q) for q in SPROUT.conf.task_queues}
    for queue in WorkflowQueue:
        assert_that(declared_names, has_item(queue.value))


@pytest.mark.smoke
def test_hud_broadcast_is_declared_as_fanout():
    """hud_broadcast must be a kombu Broadcast instance (fanout exchange) —
    a plain Queue would mean competing-consumers, not fan-out."""
    q = _queue_named(WorkflowQueue.HUD_BROADCAST.value)
    assert_that(q, instance_of(Broadcast))


@pytest.mark.smoke
def test_hud_is_a_normal_direct_queue():
    """The regular hud queue must NOT be a Broadcast — that would silently
    fan out every existing HUD task to every worker."""
    q = _queue_named(WorkflowQueue.HUD.value)
    assert_that(q, instance_of(Queue))
    assert_that(isinstance(q, Broadcast), equal_to(False))


@pytest.mark.smoke
def test_default_queue_is_set():
    """Unrouted tasks must land on the default direct queue, not auto-go
    to broadcast (which would fan out anything not explicitly routed)."""
    assert_that(SPROUT.conf.task_default_queue, equal_to(WorkflowQueue.DEFAULT.value))


# ── Routing rules ────────────────────────────────────────────────────────────

@pytest.mark.smoke
def test_broadcast_route_matches_broadcast_prefix():
    """workflows.hud.tasks.broadcast_* → hud_broadcast (fanout)."""
    routes = SPROUT.conf.task_routes
    assert_that("workflows.hud.tasks.broadcast_*" in routes, equal_to(True))
    target = routes["workflows.hud.tasks.broadcast_*"]["queue"]
    assert_that(target, equal_to(WorkflowQueue.HUD_BROADCAST.value))


@pytest.mark.smoke
def test_regular_hud_route_still_points_to_hud_queue():
    """Existing HUD tasks must still route to the direct `hud` queue,
    not accidentally pick up the broadcast pattern."""
    routes = SPROUT.conf.task_routes
    assert_that("workflows.hud.tasks.*" in routes, equal_to(True))
    assert_that(routes["workflows.hud.tasks.*"]["queue"], equal_to(WorkflowQueue.HUD.value))


@pytest.mark.smoke
def test_broadcast_route_listed_before_general_route():
    """task_routes is ordered — the more-specific broadcast pattern must come
    before the catch-all hud pattern. Otherwise broadcast tasks would
    incorrectly resolve to the regular hud queue first."""
    keys = list(SPROUT.conf.task_routes.keys())
    bcast_idx = keys.index("workflows.hud.tasks.broadcast_*")
    general_idx = keys.index("workflows.hud.tasks.*")
    assert_that(bcast_idx < general_idx, equal_to(True))


# ── The demo task itself ─────────────────────────────────────────────────────

@pytest.mark.smoke
def test_demo_broadcast_task_is_registered():
    from workflows.hud.tasks.broadcast_reload import broadcast_reload_config
    assert_that(broadcast_reload_config.name, contains_string("broadcast_reload_config"))


@pytest.mark.smoke
def test_demo_broadcast_task_runs_locally_and_returns_payload():
    """The task body must return a serialisable dict so Flower / ES log entries
    show which worker handled which fan-out. Run synchronously in-process —
    no RabbitMQ involved."""
    from workflows.hud.tasks.broadcast_reload import broadcast_reload_config
    result = broadcast_reload_config.apply(kwargs={"reason": "test"}).get()
    assert_that(result["task"], equal_to("broadcast_reload_config"))
    assert_that(result["host"], instance_of(str))
    assert_that(result["kwargs"]["reason"], equal_to("test"))
