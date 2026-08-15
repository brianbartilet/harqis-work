from __future__ import annotations

import importlib.util
import json
from pathlib import Path


def load_module():
    path = Path(__file__).resolve().parents[1] / "verify_instance_isolation.py"
    spec = importlib.util.spec_from_file_location("verify_instance_isolation_test", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _baseline(tmp_path: Path) -> dict:
    return {
        "captured_at": "2026-08-15T00:00:00+00:00",
        "primary_project": "harqis-work",
        "primary_repo": str(tmp_path / "harqis-work"),
        "container_ids": ["abc123"],
        "processes": {"42": "python primary-worker"},
    }


def test_verify_accepts_unchanged_primary_runtime(tmp_path, monkeypatch):
    module = load_module()
    snapshot = tmp_path / "baseline.json"
    baseline = _baseline(tmp_path)
    snapshot.write_text(json.dumps(baseline), encoding="utf-8")
    monkeypatch.setattr(module, "capture", lambda project, repo: dict(baseline))

    assert module.verify(snapshot) == []


def test_verify_reports_container_and_process_drift(tmp_path, monkeypatch):
    module = load_module()
    snapshot = tmp_path / "baseline.json"
    baseline = _baseline(tmp_path)
    snapshot.write_text(json.dumps(baseline), encoding="utf-8")
    monkeypatch.setattr(
        module,
        "capture",
        lambda project, repo: {**baseline, "container_ids": ["new"], "processes": {}},
    )

    assert module.verify(snapshot) == [
        "primary Compose container IDs changed",
        "primary checkout process PIDs or command lines changed",
    ]
