"""Safety and lifecycle contracts for the externally installed Nod stack."""
from __future__ import annotations

import io
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from scripts import deploy


@pytest.fixture
def nod(tmp_path, monkeypatch):
    installation = tmp_path / "installation"
    installation.mkdir()
    for name in ("compose.yaml", ".installation-ready"):
        (installation / name).touch()
    (installation / ".env").write_text("NOD_AUTH_TOKEN=test-secret\n")
    monkeypatch.setattr(Path, "is_mount", lambda self: self == tmp_path)
    monkeypatch.setattr(deploy.shutil, "which", lambda name: "/bin/docker")
    machine = {"role": "host", "nod": {"enabled": True, "mount_path": str(tmp_path),
               "compose_dir": str(installation), "health_url": "http://127.0.0.1:4310/api/health"}}
    calls = []
    state = {"running": True, "healthy": True, "api": True}

    def run(command, **kwargs):
        args = command[command.index("--env-file") + 2:]
        calls.append(args)
        assert "COMPOSE_PROJECT_NAME" not in kwargs["env"]
        if args == ["config", "--services"]:
            output = "server\npostgres\n"
        elif "--status" in args:
            output = "server\npostgres\n" if state["running"] else "postgres\n"
        elif args == ["ps", "--format", "json"]:
            output = "\n".join(json.dumps({"Service": name, "State": "running",
                "Health": "healthy" if state["healthy"] else "unhealthy"}) for name in ("server", "postgres"))
        else:
            output = ""
        return SimpleNamespace(returncode=0, stdout=output)

    def open_health(request, **kwargs):
        assert request.get_header("Authorization") == "Bearer test-secret"
        return io.StringIO(json.dumps({"ok": state["api"]}))

    monkeypatch.setattr(deploy.subprocess, "run", run)
    monkeypatch.setattr(deploy.urllib.request, "build_opener", lambda *args: SimpleNamespace(open=open_health))
    monkeypatch.setattr(deploy.time, "sleep", lambda seconds: None)
    monkeypatch.setenv("COMPOSE_PROJECT_NAME", "harqis")
    return machine, calls, state


def test_running_nod_is_only_verified(nod, capsys):
    machine, calls, _ = nod
    deploy.nod_component(machine)
    assert all(call[0] in ("config", "ps") for call in calls)
    assert "VERIFIED" in capsys.readouterr().out


def test_missing_services_start_without_recreate_build_or_pull(nod):
    machine, calls, state = nod
    state["running"] = False
    deploy.nod_component(machine)
    assert ["up", "-d", "--no-recreate", "--no-build", "--pull", "never",
            "--wait", "--wait-timeout", "180"] in calls


def test_restart_requires_explicit_action(nod):
    machine, calls, _ = nod
    deploy.nod_component(machine, "restart")
    assert ["restart"] in calls
    assert not any(call[0] in ("down", "pull", "build") for call in calls)


@pytest.mark.parametrize("action", ["status", "verify"])
def test_readonly_does_not_start_missing_services(nod, action):
    machine, calls, state = nod
    state.update(running=False, healthy=False)
    with pytest.raises(SystemExit, match="health check failed"):
        deploy.nod_component(machine, action)
    assert all(call[0] in ("config", "ps") for call in calls)


@pytest.mark.parametrize("problem", ["mount", "maintenance", "token", "outside"])
def test_preflight_failure_never_touches_docker(nod, monkeypatch, problem):
    machine, calls, _ = nod
    installation = Path(machine["nod"]["compose_dir"])
    if problem == "mount":
        monkeypatch.setattr(Path, "is_mount", lambda self: False)
    elif problem == "maintenance":
        (installation / ".maintenance").touch()
    elif problem == "token":
        (installation / ".env").write_text("")
    else:
        machine["nod"]["compose_dir"] = str(installation.parent.parent)
    with pytest.raises(SystemExit):
        deploy.nod_component(machine)
    assert not calls


def test_authentication_failure_fails_deploy_without_secret(nod):
    machine, _, state = nod
    state["api"] = False
    with pytest.raises(SystemExit, match="authenticated API health check failed") as exc:
        deploy.nod_component(machine)
    assert "test-secret" not in str(exc.value)


def test_docker_failure_redacts_output(nod, monkeypatch):
    machine, _, _ = nod
    monkeypatch.setattr(deploy.subprocess, "run", lambda *a, **k: SimpleNamespace(
        returncode=1, stdout="test-secret", stderr="test-secret"))
    with pytest.raises(SystemExit) as exc:
        deploy.nod_component(machine)
    assert "test-secret" not in str(exc.value)


@pytest.mark.parametrize("machine", [{"role": "host"}, {"role": "node", "nod": {"enabled": True}}])
def test_unconfigured_and_worker_hosts_skip_nod(machine, monkeypatch):
    monkeypatch.setattr(deploy.subprocess, "run", lambda *a, **k: pytest.fail("Docker called"))
    deploy.nod_component(machine)


def test_down_preserves_nod(nod, monkeypatch):
    machine, calls, _ = nod
    for name in ("stop_service", "emulator_down", "device_down", "docker_down"):
        monkeypatch.setattr(deploy, name, lambda *a: None)
    monkeypatch.setattr(deploy, "select_services", lambda *a: [])
    monkeypatch.setattr(deploy, "machine_env_vars", lambda *a: {})
    deploy._main(deploy.build_parser().parse_args(["--down"]), machine)
    assert not calls


def test_remote_verifies_nod_before_success():
    script = deploy.build_remote_restart_script("~/GIT/harqis-work")
    assert script.index("--verify-nod") < script.index("REMOTE HOST RESTART VERIFIED")
