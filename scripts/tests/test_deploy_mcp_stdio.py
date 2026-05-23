from __future__ import annotations

import argparse
import importlib.util
from pathlib import Path


def load_deploy_module():
    deploy_path = Path(__file__).resolve().parents[1] / "deploy.py"
    spec = importlib.util.spec_from_file_location("harqis_deploy_for_test", deploy_path)
    assert spec is not None
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_status_reports_mcp_as_stdio_on_demand_when_no_daemon(capsys, monkeypatch):
    deploy = load_deploy_module()

    monkeypatch.setattr(deploy, "read_pid", lambda service: None)
    monkeypatch.setattr(deploy, "_process_matching", lambda needle: [])

    deploy.show_status()

    output = capsys.readouterr().out
    mcp_line = next(line for line in output.splitlines() if line.startswith("mcp"))
    assert "stdio/on-demand" in mcp_line
    assert "stopped" not in mcp_line


def test_start_service_skips_mcp_daemon_spawn(capsys, monkeypatch):
    deploy = load_deploy_module()

    spawned = []
    monkeypatch.setattr(deploy, "read_pid", lambda service: None)
    monkeypatch.setattr(deploy, "spawn_detached", lambda *args, **kwargs: spawned.append((args, kwargs)) or 12345)
    monkeypatch.setattr(deploy, "machine_env_vars", lambda machine: {})

    result = deploy.start_service("mcp", {"role": "host"}, argparse.Namespace(console=False))

    assert result is True
    assert spawned == []
    assert "stdio/on-demand" in capsys.readouterr().out


def test_restart_service_does_not_spawn_mcp_daemon(capsys, monkeypatch):
    deploy = load_deploy_module()

    spawned = []
    monkeypatch.setattr(deploy, "read_pid", lambda service: None)
    monkeypatch.setattr(deploy, "spawn_detached", lambda *args, **kwargs: spawned.append((args, kwargs)) or 12345)
    monkeypatch.setattr(deploy, "machine_env_vars", lambda machine: {})
    monkeypatch.setattr(deploy, "kill_stray_processes", lambda needle, *, label: 0)

    result = deploy.restart_service("mcp", {"role": "host"}, argparse.Namespace(console=False))

    assert result is True
    assert spawned == []
    output = capsys.readouterr().out
    assert "Restart: mcp" in output
    assert "stdio/on-demand" in output
