"""Hermetic Linux supervision regressions; never contact a live manager/broker."""
import importlib.util
from pathlib import Path, PurePosixPath
from types import SimpleNamespace
from unittest.mock import Mock

import pytest


@pytest.fixture
def deploy(tmp_path, monkeypatch):
    spec = importlib.util.spec_from_file_location("deploy_systemd_test", Path(__file__).resolve().parents[1] / "deploy.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    monkeypatch.delenv("HARQIS_INSTANCE", raising=False)
    for key, value in (("IS_MAC", False), ("IS_LIN", True), ("IS_WIN", False), ("RUN_DIR", tmp_path), ("LOG_DIR", tmp_path)):
        monkeypatch.setattr(module, key, value)
    # Unit ownership describes a Linux target even on a native Windows runner.
    monkeypatch.setattr(module, "REPO_ROOT", PurePosixPath("/srv/harqis-work"))
    monkeypatch.setattr(module, "LAUNCH_PY", PurePosixPath("/srv/harqis-work/scripts/launch.py"))
    monkeypatch.setattr(module, "_systemd_unit_path", lambda s: tmp_path / module._systemd_unit_name(s))
    monkeypatch.setattr(module.subprocess, "run", Mock(return_value=SimpleNamespace(returncode=0)))
    monkeypatch.setattr(module.subprocess, "Popen", Mock(side_effect=AssertionError("unexpected spawn")))
    for name in ("stop_pid", "kill_stray_processes", "kill_stray_celery", "_close_macos_terminal_windows", "verify_worker_ready", "sync_runtime_requirements", "docker_up", "docker_down", "emulator_up", "emulator_down", "device_up", "device_down"):
        monkeypatch.setattr(module, name, Mock())
    monkeypatch.setattr(module, "read_pid", Mock(return_value=None))
    monkeypatch.setattr(module, "spawn_detached", Mock(return_value=123))
    return module


def registered(deploy, root=None):
    deploy._systemd_unit_path("worker").write_text(
        f"[Service]\nWorkingDirectory={root or deploy.REPO_ROOT}\n"
        f"ExecStart=python {deploy.LAUNCH_PY} worker\nRestart=always\n"
    )


@pytest.mark.parametrize("operation", ["start", "stop", "restart", "console", "deploy", "down"])
def test_registered_unit_stops_before_cleanup_and_recovers_without_detach(deploy, operation):
    registered(deploy)
    unit = deploy._systemd_unit_name("worker")
    stop = ["systemctl", "--user", "stop", unit]
    def cleaned(*a, **kw):
        assert any(c.args[0] == stop for c in deploy.subprocess.run.call_args_list)
    deploy.stop_pid.side_effect = cleaned
    deploy.kill_stray_processes.side_effect = cleaned
    deploy.kill_stray_celery.side_effect = cleaned
    args = deploy.build_parser().parse_args(["-c", "2"] + (["--console"] if operation == "console" else []))
    machine = {"role": "node", "queues": ["default"]}
    if operation == "stop":
        deploy.stop_service("worker")
    elif operation in ("restart", "console"):
        deploy.restart_service("worker", machine, args)
    elif operation in ("deploy", "down"):
        args.down = operation == "down"
        deploy._main(args, machine)
    else:
        deploy.start_service("worker", machine, args)
    calls = [c.args[0] for c in deploy.subprocess.run.call_args_list]
    assert stop in calls
    restarted = ["systemctl", "--user", "restart", unit] in calls
    assert restarted == (operation not in ("stop", "down", "console"))
    if operation != "console":
        deploy.spawn_detached.assert_not_called()
    for call in deploy.subprocess.run.call_args_list:
        assert call.kwargs["check"] is True
        assert 0 < call.kwargs["timeout"] <= 30


@pytest.mark.parametrize("operation", ["start", "register", "unregister"])
def test_foreign_unit_preserved_without_manager_mutation(deploy, operation):
    registered(deploy, "/foreign/checkout")
    original = deploy._systemd_unit_path("worker").read_bytes()
    args = deploy.build_parser().parse_args([])
    with pytest.raises(RuntimeError, match="checkout"):
        if operation == "start":
            deploy.start_service("worker", {}, args)
        elif operation == "register":
            deploy.register_services({}, args, ["worker"])
        else:
            deploy.unregister_services(["worker"])
    assert deploy._systemd_unit_path("worker").read_bytes() == original
    deploy.subprocess.run.assert_not_called()
    deploy.spawn_detached.assert_not_called()


@pytest.mark.parametrize("platform", ["IS_LIN", "IS_WIN", "IS_MAC"])
def test_stdio_never_registered_on_any_platform(deploy, monkeypatch, platform):
    for name in ("IS_LIN", "IS_WIN", "IS_MAC"):
        monkeypatch.setattr(deploy, name, name == platform)
    backends = [Mock(), Mock(), Mock()]
    for name, backend in zip(("_register_systemd", "_register_scheduled_tasks", "_register_launchd"), backends):
        monkeypatch.setattr(deploy, name, backend)
    deploy.register_services({}, deploy.build_parser().parse_args([]), ["mcp"])
    for backend in backends:
        if backend.called:
            assert backend.call_args.args[2] == []


def test_systemd_quotes_arguments_environment_and_roundtrips_ownership(deploy, monkeypatch, tmp_path):
    root = tmp_path / 'repo space%cash$quote"'
    monkeypatch.setattr(deploy, "REPO_ROOT", root)
    monkeypatch.setattr(deploy, "LAUNCH_PY", root / "scripts/launch.py")
    monkeypatch.setattr(deploy, "python_exe", lambda **kw: str(root / ".venv/bin/python"))
    monkeypatch.setenv("HARQIS_QUEUE_PREFIX", "special%prefix")
    args = deploy.build_parser().parse_args(["--queues", "cash$queue%name", "-c", "3"])
    deploy.register_services({"env_vars": {"SPECIAL": 'a b"c\\d\n$e%f'}}, args, ["worker"])
    text = deploy._systemd_unit_path("worker").read_text()
    assert '"cash$$queue%%name"' in text
    assert f"WorkingDirectory={str(root).replace('%', '%%')}\n" in text
    assert f"StandardOutput=append:{deploy.log_path('worker')}\n" in text
    assert 'Environment="HARQIS_QUEUE_PREFIX=special%%prefix"' in text
    assert 'Environment="WORKFLOW_CONCURRENCY=3"' in text
    assert 'Environment="SPECIAL=a b\\"c\\\\d\\n$e%%f"' in text
    assert deploy._registered_systemd_path("worker") == deploy._systemd_unit_path("worker")


@pytest.mark.parametrize("action", ["stop", "daemon-reload", "enable", "restart"])
def test_manager_failure_aborts_without_detached_fallback(deploy, action):
    registered(deploy)
    def run(cmd, **kwargs):
        if cmd[2] == action:
            raise deploy.subprocess.CalledProcessError(1, cmd)
        return SimpleNamespace(returncode=0)
    deploy.subprocess.run.side_effect = run
    with pytest.raises(deploy.subprocess.CalledProcessError):
        deploy.start_service("worker", {}, deploy.build_parser().parse_args([]))
    deploy.spawn_detached.assert_not_called()
    deploy.verify_worker_ready.assert_not_called()
    if action == "stop":
        deploy.kill_stray_processes.assert_not_called()


@pytest.mark.parametrize("down", [False, True])
def test_scheduler_only_does_not_sweep_unselected_workers(deploy, down):
    registered(deploy)
    args = deploy.build_parser().parse_args(["--scheduler"])
    args.down = down
    deploy._main(args, {"role": "node", "queues": ["default"]})
    deploy.kill_stray_celery.assert_not_called()
    assert all(c.kwargs["label"] != "worker" for c in deploy.kill_stray_processes.call_args_list)
    assert not any(deploy._systemd_unit_name("worker") in c.args[0] for c in deploy.subprocess.run.call_args_list)


def test_rebuild_refuses_foreign_systemd_unit_before_manager_calls(deploy):
    registered(deploy, "/foreign/checkout")
    with pytest.raises(RuntimeError, match="checkout"):
        deploy._suspend_supervised_services()
    deploy.subprocess.run.assert_not_called()
