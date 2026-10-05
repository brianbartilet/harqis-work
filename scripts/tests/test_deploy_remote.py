from __future__ import annotations

import importlib.util
from pathlib import Path
from types import SimpleNamespace

import pytest


def load_deploy_module():
    deploy_path = Path(__file__).resolve().parents[1] / "deploy.py"
    spec = importlib.util.spec_from_file_location("harqis_deploy_remote_test", deploy_path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_remote_option_is_parsed():
    deploy = load_deploy_module()

    parsed = deploy.build_parser().parse_args(["--remote", "harqis-mac-mini"])

    assert parsed.remote == "harqis-mac-mini"


def test_load_remote_target_reads_ssh_table(tmp_path, monkeypatch):
    deploy = load_deploy_module()
    machines = tmp_path / "machines.toml"
    machines.write_text("[default]\nrole = \"host\"\n", encoding="utf-8")
    machines.with_suffix(".local.toml").write_text(
        """[ssh.harqis-mac-mini]
user = "harqis-one"
host = "harqis-ones-mac-mini"
path = "~/GIT/harqis-work"
""",
        encoding="utf-8",
    )
    monkeypatch.setattr(deploy, "MACHINES_TOML", machines)

    assert deploy.load_remote_target("harqis-mac-mini") == {
        "user": "harqis-one",
        "host": "harqis-ones-mac-mini",
        "path": "~/GIT/harqis-work",
    }


def test_remote_restart_script_contains_required_verified_workflow():
    deploy = load_deploy_module()

    script = deploy.build_remote_restart_script("~/GIT/harqis-work")

    assert 'repo="$HOME"/GIT/harqis-work' in script
    assert "git branch --show-current" in script
    assert "git rev-parse HEAD" in script
    assert "git status --short --branch" in script
    assert 'git -c core.hooksPath=/dev/null pull --ff-only' in script
    assert "/Applications/Docker.app/Contents/Resources/bin" in script
    assert "scripts/deploy.py --role host --down" in script
    assert "scripts/deploy.py --role host\n" in script
    assert "--console" not in script
    assert 'os.environ.get("FRONTEND_PORT", "8081")' in script
    assert "for service in rabbitmq redis elasticsearch" in script
    assert "from scripts.launch import setup_env" in script
    assert 'verify_worker_ready("worker", machine, args)' in script
    assert "if not pings" not in script
    assert "REMOTE HOST RESTART VERIFIED" in script


def test_remote_verified_restart_streams_script_over_ssh(monkeypatch):
    deploy = load_deploy_module()
    monkeypatch.setattr(deploy.shutil, "which", lambda name: f"/mock/bin/{name}")
    observed = {}
    monkeypatch.setattr(
        deploy,
        "load_remote_target",
        lambda key: {
            "user": "harqis-one",
            "host": "harqis-host",
            "path": "/Users/harqis-one/GIT/harqis-work",
        },
    )

    def fake_run(command, **kwargs):
        observed["command"] = command
        observed["kwargs"] = kwargs
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(deploy.subprocess, "run", fake_run)

    deploy.remote_verified_restart("harqis-mac-mini")

    assert observed["command"] == [
        "ssh",
        "-o",
        "ConnectTimeout=10",
        "harqis-one@harqis-host",
        "bash -s",
    ]
    payload = observed["kwargs"]["input"]
    assert isinstance(payload, bytes)
    assert b"git -c core.hooksPath=/dev/null pull --ff-only" in payload
    assert b"\r\n" not in payload
    assert "text" not in observed["kwargs"]
    assert observed["kwargs"]["check"] is False


def test_remote_restart_failure_is_reported(monkeypatch):
    deploy = load_deploy_module()
    monkeypatch.setattr(deploy.shutil, "which", lambda name: f"/mock/bin/{name}")
    monkeypatch.setattr(
        deploy,
        "load_remote_target",
        lambda key: {"user": "u", "host": "host", "path": "/srv/harqis"},
    )
    monkeypatch.setattr(
        deploy.subprocess,
        "run",
        lambda *args, **kwargs: SimpleNamespace(returncode=22),
    )

    with pytest.raises(RuntimeError, match="ssh exit 22"):
        deploy.remote_verified_restart("host")
