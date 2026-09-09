from __future__ import annotations

import glob
import importlib.util
import shelve
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


def test_beat_schedule_without_entries_is_rotated(tmp_path, monkeypatch):
    launch = load_launch_module()
    base = tmp_path / "celerybeat-schedule"
    with shelve.open(str(base)) as db:
        db["tz"] = "Asia/Singapore"
        db["__version__"] = "5.6.3"
    original_paths = set(glob.glob(str(base) + "*"))

    monkeypatch.setattr(launch, "_beat_schedule_base", lambda: base)

    launch._heal_beat_schedule()

    remaining_paths = set(glob.glob(str(base) + "*"))
    assert original_paths
    assert original_paths.isdisjoint(remaining_paths)
    assert any(".corrupt-" in path for path in remaining_paths)


def test_setup_env_adds_repo_to_live_python_import_path(monkeypatch):
    launch = load_launch_module()
    monkeypatch.setattr(launch, "load_env_file", lambda: {})
    monkeypatch.setattr(launch, "_machine_env_vars", lambda: {})
    monkeypatch.setattr(launch.sys, "path", [])

    launch.setup_env()

    assert str(launch.REPO_ROOT) in launch.sys.path
    assert str(launch.SCRIPTS_DIR) in launch.sys.path
