from __future__ import annotations

import argparse
import importlib.util
from pathlib import Path
from types import SimpleNamespace

import pytest


def load_deploy_module():
    deploy_path = Path(__file__).resolve().parents[1] / "deploy.py"
    spec = importlib.util.spec_from_file_location("harqis_deploy_rebuild_test", deploy_path)
    assert spec is not None
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def _args() -> argparse.Namespace:
    return argparse.Namespace(console=False, queues=None, profile=None, num_agents=None)


def test_rebuild_venv_is_a_lifecycle_flag():
    deploy = load_deploy_module()

    parsed = deploy.build_parser().parse_args(["--rebuild-venv"])

    assert parsed.rebuild_venv is True
    with pytest.raises(SystemExit):
        deploy.build_parser().parse_args(["--rebuild-venv", "--status"])


def test_running_from_target_venv_uses_resolved_prefix(tmp_path, monkeypatch):
    deploy = load_deploy_module()
    venv = tmp_path / ".venv"
    venv.mkdir()
    monkeypatch.setattr(deploy, "VENV_DIR", venv)
    monkeypatch.setattr(deploy.sys, "prefix", str(venv))

    assert deploy._running_from_target_venv() is True


@pytest.mark.parametrize(
    ("is_win", "expected_parts"),
    [(True, ("Scripts", "python.exe")), (False, ("bin", "python"))],
)
def test_venv_python_path_is_cross_platform(tmp_path, monkeypatch, is_win, expected_parts):
    deploy = load_deploy_module()
    monkeypatch.setattr(deploy, "VENV_DIR", tmp_path / ".venv")
    monkeypatch.setattr(deploy, "IS_WIN", is_win)

    assert deploy._venv_console_python().parts[-2:] == expected_parts


@pytest.mark.parametrize("platform", ["windows", "mac", "linux"])
def test_supervision_pause_and_resume_are_platform_scoped(tmp_path, monkeypatch, platform):
    deploy = load_deploy_module()
    calls = []
    plist = tmp_path / "work.harqis.worker.plist"
    plist.write_text("plist", encoding="utf-8")

    monkeypatch.setattr(deploy, "IS_WIN", platform == "windows")
    monkeypatch.setattr(deploy, "IS_MAC", platform == "mac")
    monkeypatch.setattr(deploy, "IS_LIN", platform == "linux")
    monkeypatch.setattr(deploy, "_plist_path", lambda service: plist)

    def fake_run(command, **kwargs):
        calls.append(command)
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(deploy.subprocess, "run", fake_run)
    active = deploy._suspend_supervised_services()
    deploy._resume_supervised_services(active)

    if platform == "windows":
        assert active == set()
        assert calls == []
    elif platform == "mac":
        assert "worker" in active
        assert any(command[:2] == ["launchctl", "unload"] for command in calls)
        assert any(command[:2] == ["launchctl", "load"] for command in calls)
    else:
        assert "worker" in active
        assert any("is-active" in command for command in calls)
        assert any("stop" in command for command in calls)
        assert any("start" in command for command in calls)


def test_rebuild_keeps_backup_and_restores_running_services(tmp_path, monkeypatch):
    deploy = load_deploy_module()
    venv = tmp_path / ".venv"
    venv.mkdir()
    (venv / "old.txt").write_text("old", encoding="utf-8")
    requirements = tmp_path / "requirements.txt"
    requirements.write_text("", encoding="utf-8")
    restored = []

    monkeypatch.setattr(deploy, "VENV_DIR", venv)
    monkeypatch.setattr(deploy, "REQUIREMENTS_FILE", requirements)
    monkeypatch.setattr(deploy, "LOG_DIR", tmp_path / "logs")
    monkeypatch.setattr(deploy, "_record_running_services", lambda: {"worker"})
    monkeypatch.setattr(deploy, "_suspend_supervised_services", lambda active=None: set())
    monkeypatch.setattr(deploy, "_quiesce_services", lambda services: None)
    monkeypatch.setattr(
        deploy,
        "_create_clean_venv",
        lambda base, log: (venv.mkdir(), (venv / "new.txt").write_text("new")),
    )
    monkeypatch.setattr(deploy, "_install_venv_requirements", lambda log: None)
    monkeypatch.setattr(deploy, "_verify_clean_venv", lambda log: None)
    monkeypatch.setattr(
        deploy,
        "_restore_service_snapshot",
        lambda running, supervised, machine, args: restored.append((running, supervised)),
    )

    backup = deploy.rebuild_virtualenv({"role": "node"}, _args())

    assert backup is not None
    assert (backup / "old.txt").read_text(encoding="utf-8") == "old"
    assert (venv / "new.txt").read_text(encoding="utf-8") == "new"
    assert restored == [({"worker"}, set())]


def test_rebuild_rolls_back_when_install_fails(tmp_path, monkeypatch):
    deploy = load_deploy_module()
    venv = tmp_path / ".venv"
    venv.mkdir()
    (venv / "old.txt").write_text("old", encoding="utf-8")
    requirements = tmp_path / "requirements.txt"
    requirements.write_text("", encoding="utf-8")
    restored = []

    monkeypatch.setattr(deploy, "VENV_DIR", venv)
    monkeypatch.setattr(deploy, "REQUIREMENTS_FILE", requirements)
    monkeypatch.setattr(deploy, "LOG_DIR", tmp_path / "logs")
    monkeypatch.setattr(deploy, "_record_running_services", lambda: {"worker"})
    monkeypatch.setattr(deploy, "_suspend_supervised_services", lambda active=None: set())
    monkeypatch.setattr(deploy, "_quiesce_services", lambda services: None)
    monkeypatch.setattr(
        deploy,
        "_create_clean_venv",
        lambda base, log: (venv.mkdir(), (venv / "new.txt").write_text("new")),
    )

    def fail_install(log):
        raise RuntimeError("resolver failed")

    monkeypatch.setattr(deploy, "_install_venv_requirements", fail_install)
    monkeypatch.setattr(
        deploy,
        "_restore_service_snapshot",
        lambda running, supervised, machine, args: restored.append((running, supervised)),
    )

    with pytest.raises(RuntimeError, match="rolled back"):
        deploy.rebuild_virtualenv({"role": "node"}, _args())

    assert (venv / "old.txt").read_text(encoding="utf-8") == "old"
    failed = list(tmp_path.glob(".venv.failed-*"))
    assert len(failed) == 1
    assert (failed[0] / "new.txt").read_text(encoding="utf-8") == "new"
    assert restored == [({"worker"}, set())]
