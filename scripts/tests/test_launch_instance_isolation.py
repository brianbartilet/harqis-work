from __future__ import annotations

import importlib.util
from pathlib import Path


def load_launch_module():
    path = Path(__file__).resolve().parents[1] / "launch.py"
    spec = importlib.util.spec_from_file_location("launch_instance_isolation_test", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_upstream_beat_schedule_path_remains_compatible(monkeypatch):
    monkeypatch.delenv("HARQIS_INSTANCE", raising=False)
    launch = load_launch_module()

    assert launch._beat_schedule_base() == launch.REPO_ROOT / "celerybeat-schedule"


def test_fork_beat_schedule_lives_under_instance_data_root(tmp_path, monkeypatch):
    monkeypatch.setenv("HARQIS_INSTANCE", "alam-tech-labs")
    monkeypatch.setenv("HARQIS_DATA_ROOT", str(tmp_path))
    launch = load_launch_module()

    assert launch._beat_schedule_base() == tmp_path / "runtime" / "celerybeat-schedule"
    assert (tmp_path / "runtime").is_dir()
