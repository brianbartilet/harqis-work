from __future__ import annotations

import importlib.util
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest


@pytest.fixture
def launch(monkeypatch):
    path = Path(__file__).resolve().parents[1] / "launch.py"
    spec = importlib.util.spec_from_file_location("launch_readiness_test", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    monkeypatch.setattr(module, "setup_env", Mock())
    return module


def app_with_replies(pings, queues):
    inspect = Mock()
    inspect.ping.return_value = pings
    inspect.active_queues.return_value = queues
    app = SimpleNamespace(
        control=SimpleNamespace(inspect=Mock(return_value=inspect)),
        amqp=SimpleNamespace(queues={
            "default": SimpleNamespace(name="default", exchange=SimpleNamespace(type="direct", name="default")),
            "events": SimpleNamespace(name="bcast.config-uuid", exchange=SimpleNamespace(type="fanout", name="events")),
        }),
    )
    return app, inspect


@pytest.mark.parametrize("pings,queues,expected", [
    ({"celery@remote": {"ok": "pong"}}, {"celery@remote": [{"name": "default"}]}, "ping"),
    ({"celery@local": {"ok": "pong"}}, {"celery@remote": [{"name": "default"}]}, "default"),
    ({"celery@local": {"ok": "pong"}}, {"celery@local": [{"name": "default"}]}, "events"),
    ({"celery@local": {"ok": "pong"}}, {"celery@local": [{"name": "default"}, {"name": "events", "exchange": {"type": "direct", "name": "events"}}]}, "events"),
])
def test_worker_gate_rejects_remote_or_incomplete_local_worker(launch, monkeypatch, pings, queues, expected):
    app, inspector = app_with_replies(pings, queues)
    # One attempt, then the monotonic deadline expires. No sleep or network.
    clock = Mock(side_effect=[0, 0, 2])
    monkeypatch.setattr(launch.time, "monotonic", clock)
    monkeypatch.setattr(launch.time, "sleep", Mock())
    with pytest.raises(RuntimeError, match=expected):
        launch.wait_for_worker(app, "celery@local", ["default", "events"], timeout=1)
    app.control.inspect.assert_called_once_with(destination=["celery@local"], timeout=0.5)


def test_fanout_is_matched_by_exchange_not_ephemeral_name(launch):
    app, inspector = app_with_replies(
        {"celery@local": {"ok": "pong"}},
        {"celery@local": [{"name": "default"}, {"name": "bcast.live-uuid", "exchange": {"type": "fanout", "name": "events"}}]},
    )
    launch.wait_for_worker(app, "celery@local", ["default", "events"])
    inspector.ping.assert_called_once()
    inspector.active_queues.assert_called_once()


def test_transient_inspection_failure_retries_without_leaking_secrets(launch, monkeypatch):
    app, inspector = app_with_replies({"celery@local": {"ok": "pong"}}, {"celery@local": [{"name": "default"}]})
    inspector.ping.side_effect = [ConnectionError("secret-broker-url"), {"celery@local": {"ok": "pong"}}]
    monkeypatch.setattr(launch.time, "sleep", Mock())
    launch.wait_for_worker(app, "celery@local", ["default"])
    assert inspector.ping.call_count == 2
    launch.time.sleep.assert_called_once()


@pytest.mark.parametrize("hostname,expected", [(None, "celery@local"), ("capture@%h", "capture@local")])
def test_worker_check_bootstraps_env_then_qualifies_queues(launch, monkeypatch, hostname, expected):
    import sys
    from celery.utils import nodenames
    monkeypatch.setattr(nodenames, "gethostname", lambda: "local")
    app = object()
    monkeypatch.setitem(sys.modules, "core.apps.sprout", SimpleNamespace(SPROUT=app))
    monkeypatch.setattr(launch, "wait_for_worker", Mock())
    def setup():
        monkeypatch.setenv("HARQIS_QUEUE_PREFIX", "test")
    launch.setup_env.side_effect = setup
    args = launch.build_parser().parse_args(["worker-check", "--queues", "default, events"] + (["--hostname", hostname] if hostname else []))
    args.func(args)
    launch.wait_for_worker.assert_called_once_with(app, expected, ["test.default", "test.events"])
