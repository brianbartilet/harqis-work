"""Lifecycle tests are hermetic: no launchctl, Docker, subprocess or PID mutation."""
from __future__ import annotations

import importlib.util
import plistlib
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest


@pytest.fixture
def deploy(tmp_path, monkeypatch):
    path = Path(__file__).resolve().parents[1] / "deploy.py"
    spec = importlib.util.spec_from_file_location("deploy_reliability_test", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    assert module.REPO_ROOT == path.parent.parent
    monkeypatch.delenv("HARQIS_INSTANCE", raising=False)
    monkeypatch.setattr(module, "IS_MAC", True)
    monkeypatch.setattr(module, "IS_LIN", False)
    monkeypatch.setattr(module, "IS_WIN", False)
    monkeypatch.setattr(module, "RUN_DIR", tmp_path)
    monkeypatch.setattr(module, "LOG_DIR", tmp_path)
    monkeypatch.setattr(module, "SCRIPTS_DIR", tmp_path)
    monkeypatch.setattr(module, "_plist_path", lambda s: tmp_path / f"{s}.plist")
    monkeypatch.setattr(module.subprocess, "run", Mock(side_effect=AssertionError("unexpected subprocess")))
    monkeypatch.setattr(module.subprocess, "Popen", Mock(side_effect=AssertionError("unexpected spawn")))
    for name in ("_close_macos_terminal_windows", "kill_stray_celery", "kill_stray_processes",
                 "stop_pid", "sync_runtime_requirements", "docker_up", "docker_down",
                 "_bootstrap_elasticsearch", "emulator_up", "emulator_down", "device_up", "device_down"):
        monkeypatch.setattr(module, name, Mock())
    monkeypatch.setattr(module, "read_pid", Mock(return_value=None))
    monkeypatch.setattr(module, "spawn_detached", Mock(return_value=123))
    return module


def registered(deploy, service="worker", **updates):
    data = {"Label": deploy._service_label(service),
            "WorkingDirectory": str(deploy.REPO_ROOT),
            "ProgramArguments": ["python", str(deploy.LAUNCH_PY), service],
            "KeepAlive": True}
    data.update(updates)
    deploy._plist_path(service).write_bytes(plistlib.dumps(data))


def launchctl(deploy, loaded=False):
    calls = []
    def run(cmd, **kwargs):
        nonlocal loaded
        calls.append(cmd)
        assert cmd[0] == "launchctl"
        if cmd[1] == "list":
            return SimpleNamespace(returncode=0 if loaded else 1)
        if cmd[1] == "unload":
            loaded = False
        elif cmd[1] == "load":
            loaded = True
        else:
            pytest.fail(f"unexpected command: {cmd}")
        return SimpleNamespace(returncode=0)
    deploy.subprocess.run.side_effect = run
    return calls


def test_unloaded_registered_worker_is_reactivated_not_detached(deploy, monkeypatch):
    registered(deploy)
    calls = launchctl(deploy)
    # Readiness is exercised separately without contacting the broker.
    monkeypatch.setattr(deploy, "verify_worker_ready", Mock(), raising=False)
    args = deploy.build_parser().parse_args([])
    assert deploy.start_service("worker", {"queues": ["default"]}, args)
    assert ["launchctl", "load", str(deploy._plist_path("worker"))] in calls
    deploy.spawn_detached.assert_not_called()


@pytest.mark.parametrize("operation", ["stop", "restart", "deploy", "down", "console"])
def test_launchd_is_unloaded_before_process_cleanup(deploy, monkeypatch, operation):
    registered(deploy)
    calls = launchctl(deploy, loaded=True)
    unload = ["launchctl", "unload", str(deploy._plist_path("worker"))]
    def assert_unloaded(*a, **kw):
        assert unload in calls, "KeepAlive must be disabled before killing processes"
    deploy.stop_pid.side_effect = assert_unloaded
    deploy.kill_stray_processes.side_effect = assert_unloaded
    deploy.kill_stray_celery.side_effect = assert_unloaded
    deploy.read_pid.return_value = 321
    monkeypatch.setattr(deploy, "verify_worker_ready", Mock(), raising=False)
    args = deploy.build_parser().parse_args(["-c", "2"] + (["--console"] if operation == "console" else []))
    if operation == "stop":
        deploy.stop_service("worker")
    elif operation in ("restart", "console"):
        deploy.restart_service("worker", {"queues": ["default"]}, args)
    else:
        args.down = operation == "down"
        deploy._main(args, {"role": "node", "queues": ["default"]})
    assert unload in calls
    if operation in ("stop", "down", "console"):
        assert not any(c[1] == "load" for c in calls)


def test_foreign_registration_is_not_overwritten_or_started(deploy):
    registered(deploy, WorkingDirectory="/another/checkout")
    original = deploy._plist_path("worker").read_bytes()
    with pytest.raises(RuntimeError, match="checkout"):
        deploy.start_service("worker", {}, deploy.build_parser().parse_args([]))
    assert deploy._plist_path("worker").read_bytes() == original
    deploy.spawn_detached.assert_not_called()
    deploy.subprocess.run.assert_not_called()


def test_launchctl_load_failure_is_not_reported_as_success(deploy):
    registered(deploy)
    def run(cmd, **kwargs):
        if cmd[1] == "load" and kwargs.get("check"):
            raise deploy.subprocess.CalledProcessError(5, cmd)
        return SimpleNamespace(returncode=1)
    deploy.subprocess.run.side_effect = run
    with pytest.raises(deploy.subprocess.CalledProcessError):
        deploy.start_service("worker", {}, deploy.build_parser().parse_args([]))
    deploy.spawn_detached.assert_not_called()


@pytest.mark.parametrize("mode", ["detached", "registered", "register", "console", "restart", "already-running"])
def test_no_worker_success_before_readiness(deploy, monkeypatch, capsys, mode):
    if mode == "registered":
        registered(deploy)
    if mode in ("registered", "register"):
        launchctl(deploy)
    if mode == "already-running":
        deploy.read_pid.return_value = 123
    gate = Mock(side_effect=RuntimeError("local worker not ready"))
    monkeypatch.setattr(deploy, "verify_worker_ready", gate, raising=False)
    flags = ["-c", "2"]
    if mode in ("console", "register"):
        flags.append("--" + mode)
    if mode == "restart":
        flags += ["--restart", "worker"]
    with pytest.raises(RuntimeError, match="local worker not ready"):
        deploy._main(deploy.build_parser().parse_args(flags), {"role": "node", "queues": ["default"]})
    gate.assert_called_once()
    output = capsys.readouterr().out
    assert "Started:" not in output
    assert "Started 1" not in output
    assert "Already running:" not in output


def test_readiness_subprocess_uses_same_queue_and_node_with_hard_timeout(deploy):
    deploy.subprocess.run.side_effect = None
    deploy.subprocess.run.return_value = SimpleNamespace(returncode=0)
    args = deploy.build_parser().parse_args(["--queues", "default,hfl"])
    deploy.verify_worker_ready("worker", {}, args)
    command = deploy.subprocess.run.call_args.args[0]
    assert command[1:] == [str(deploy.LAUNCH_PY), "worker-check", "--queues", "default,hfl"]
    assert deploy.subprocess.run.call_args.kwargs["timeout"] == 75
    assert deploy.subprocess.run.call_args.kwargs["cwd"] == deploy.REPO_ROOT


def test_readiness_timeout_fails_closed_with_log_pointer(deploy):
    deploy.subprocess.run.side_effect = deploy.subprocess.TimeoutExpired("worker-check", 75)
    with pytest.raises(RuntimeError, match="worker.log"):
        deploy.verify_worker_ready("worker", {}, deploy.build_parser().parse_args([]))


def test_registered_plist_preserves_topology_environment_and_cli_concurrency(deploy, monkeypatch):
    registered(deploy)
    launchctl(deploy)
    monkeypatch.setenv("HARQIS_QUEUE_PREFIX", "test-instance")
    args = deploy.build_parser().parse_args(["-c", "3", "--queues", "default,hfl"])
    deploy._register_launchd({"env_vars": {"HFL_PATH": "a&b"}}, args, ["worker"])
    plist = plistlib.loads(deploy._plist_path("worker").read_bytes())
    assert plist["EnvironmentVariables"]["HFL_PATH"] == "a&b"
    assert plist["EnvironmentVariables"]["HARQIS_QUEUE_PREFIX"] == "test-instance"
    assert plist["EnvironmentVariables"]["WORKFLOW_CONCURRENCY"] == "3"
    assert plist["ProgramArguments"][-2:] == ["--queues", "default,hfl"]


def test_console_keeps_registered_nonconsole_service_unsupervised(deploy, monkeypatch):
    registered(deploy, "frontend")
    calls = launchctl(deploy, loaded=True)
    args = deploy.build_parser().parse_args(["--console"])
    deploy.start_service("frontend", {}, args)
    assert not any(c[1] == "load" for c in calls)
    deploy.spawn_detached.assert_called_once()


def test_stdio_is_not_registered(deploy):
    deploy._register_launchd({}, deploy.build_parser().parse_args([]), ["mcp"])
    assert not deploy._plist_path("mcp").exists()
    deploy.subprocess.run.assert_not_called()
