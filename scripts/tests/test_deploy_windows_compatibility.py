"""Native Windows contracts; all process/registry operations are mocked."""
from __future__ import annotations

import importlib.util
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest


@pytest.fixture
def deploy(tmp_path, monkeypatch):
    path = Path(__file__).resolve().parents[1] / "deploy.py"
    spec = importlib.util.spec_from_file_location("windows_deploy_contract", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    for name, value in (("IS_WIN", True), ("IS_MAC", False), ("IS_LIN", False)):
        monkeypatch.setattr(module, name, value)
    monkeypatch.setattr(module, "RUN_DIR", tmp_path / "run")
    monkeypatch.setattr(module, "LOG_DIR", tmp_path / "logs")
    module.RUN_DIR.mkdir()
    module.LOG_DIR.mkdir()
    monkeypatch.setattr(module.subprocess, "run", Mock(side_effect=AssertionError("unexpected external command")))
    return module


def test_windows_stdio_endpoint_is_not_registered(deploy):
    deploy.register_services({}, deploy.build_parser().parse_args([]), ["mcp"])
    deploy.subprocess.run.assert_not_called()


def test_windows_registration_failure_is_not_reported_as_success(deploy):
    deploy.subprocess.run.side_effect = None
    deploy.subprocess.run.return_value = SimpleNamespace(returncode=5, stdout="", stderr="Access denied")
    with pytest.raises((RuntimeError, deploy.subprocess.CalledProcessError)):
        deploy.register_services({}, deploy.build_parser().parse_args([]), ["worker"])


def test_windows_registry_errors_terminate_powershell(deploy):
    deploy.subprocess.run.side_effect = None
    deploy.subprocess.run.return_value = SimpleNamespace(returncode=0)
    deploy.register_services({}, deploy.build_parser().parse_args([]), ["worker"])
    command = deploy.subprocess.run.call_args.args[0][-1]
    assert "$ErrorActionPreference = 'Stop'" in command


def test_windows_probe_uses_console_python_with_paths_containing_spaces(deploy, tmp_path, monkeypatch):
    root = tmp_path / "Server Apps" / "HARQIS Work"
    python = root / ".venv" / "Scripts" / "python.exe"
    python.parent.mkdir(parents=True)
    python.touch()
    pythonw = python.with_name("pythonw.exe")
    pythonw.touch()
    monkeypatch.setattr(deploy, "REPO_ROOT", root)
    monkeypatch.setattr(deploy, "VENV_PY", pythonw)
    monkeypatch.setattr(deploy, "LAUNCH_PY", root / "scripts" / "launch.py")
    deploy.subprocess.run.side_effect = None
    deploy.subprocess.run.return_value = SimpleNamespace(returncode=0)
    deploy.verify_worker_ready("worker", {}, deploy.build_parser().parse_args(["--queues", "default,hfl"]))
    call = deploy.subprocess.run.call_args
    assert call.args[0] == [str(python), str(root / "scripts" / "launch.py"),
                            "worker-check", "--queues", "default,hfl"]
    assert call.kwargs["check"] is True
    assert call.kwargs["timeout"] == 75
    assert not call.kwargs.get("shell", False)


@pytest.mark.parametrize("console", [False, True])
def test_windows_spawn_preserves_native_process_flags(deploy, tmp_path, monkeypatch, console):
    # Constants only exist on actual Windows; inject them for Unix test hosts.
    for name, value in (("CREATE_NEW_CONSOLE", 16), ("CREATE_NEW_PROCESS_GROUP", 512),
                        ("CREATE_NO_WINDOW", 134217728)):
        monkeypatch.setattr(deploy.subprocess, name, value, raising=False)
    popen = Mock(return_value=SimpleNamespace(pid=123))
    monkeypatch.setattr(deploy.subprocess, "Popen", popen)
    assert deploy.spawn_detached(["python.exe", "launch.py", "worker"],
                                 tmp_path / "worker.log", show_console=console) == 123
    kwargs = popen.call_args.kwargs
    expected = deploy.subprocess.CREATE_NEW_CONSOLE if console else deploy.subprocess.CREATE_NO_WINDOW
    assert kwargs["creationflags"] == expected | deploy.subprocess.CREATE_NEW_PROCESS_GROUP
    assert "start_new_session" not in kwargs
    if not console:
        kwargs["stdout"].close()


def test_windows_worker_start_never_invokes_unix_supervisors(deploy, monkeypatch):
    monkeypatch.setattr(deploy, "read_pid", lambda service: None)
    monkeypatch.setattr(deploy, "spawn_detached", Mock(return_value=123))
    gate = Mock()
    monkeypatch.setattr(deploy, "verify_worker_ready", gate)
    deploy.start_service("worker", {}, deploy.build_parser().parse_args([]))
    gate.assert_called_once()
    deploy.subprocess.run.assert_not_called()
