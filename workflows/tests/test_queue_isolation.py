from __future__ import annotations

import importlib.util
from pathlib import Path


def load_queues_module(name: str):
    path = Path(__file__).resolve().parents[1] / "queues.py"
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_upstream_queue_names_remain_compatible(monkeypatch):
    monkeypatch.delenv("HARQIS_INSTANCE", raising=False)
    monkeypatch.delenv("HARQIS_QUEUE_PREFIX", raising=False)
    queues = load_queues_module("queues_default_test")

    assert queues.WorkflowQueue.DEFAULT.value == "default"
    assert queues.qualify_queues("default,adhoc") == "default,adhoc"


def test_configured_queues_are_instance_scoped(monkeypatch):
    monkeypatch.setenv("HARQIS_INSTANCE", "ALAM Tech Labs")
    monkeypatch.delenv("HARQIS_QUEUE_PREFIX", raising=False)
    queues = load_queues_module("queues_isolated_test")

    assert queues.WorkflowQueue.DEFAULT.value == "alam-tech-labs.default"
    assert queues.WorkflowQueue.ADHOC.value == "alam-tech-labs.adhoc"
    assert queues.qualify_queue("default") == "alam-tech-labs.default"
    assert queues.qualify_queues("default,other.default") == (
        "alam-tech-labs.default,alam-tech-labs.other.default"
    )
    assert queues.qualify_queue("alam-tech-labs.default") == "alam-tech-labs.default"
