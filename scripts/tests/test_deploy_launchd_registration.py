from __future__ import annotations

import argparse
import importlib.util
from pathlib import Path


def load_deploy_module():
    deploy_path = Path(__file__).resolve().parents[1] / "deploy.py"
    spec = importlib.util.spec_from_file_location("harqis_deploy_launchd_test", deploy_path)
    assert spec is not None
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_register_launchd_removes_obsolete_bootstrap_job(tmp_path, monkeypatch):
    deploy = load_deploy_module()
    monkeypatch.setenv("HOME", str(tmp_path))
    launch_agents = tmp_path / "Library" / "LaunchAgents"
    launch_agents.mkdir(parents=True)
    legacy = launch_agents / "work.harqis.deploy.plist"
    legacy.write_text(
        """<?xml version="1.0" encoding="UTF-8"?>
<plist version="1.0"><dict>
  <key>Label</key><string>work.harqis.deploy</string>
  <key>ProgramArguments</key><array>
    <string>/bin/bash</string>
    <string>/Users/example/harqis-work/scripts/sh/deploy.sh</string>
  </array>
</dict></plist>
""",
        encoding="utf-8",
    )
    calls: list[list[str]] = []

    def fake_run(command, **kwargs):
        calls.append(command)
        return type("Result", (), {"returncode": 0})()

    monkeypatch.setattr(deploy.subprocess, "run", fake_run)

    deploy._register_launchd({}, argparse.Namespace(), [], load=True)

    assert not legacy.exists()
    assert ["launchctl", "unload", str(legacy)] in calls


def test_register_launchd_preserves_nonlegacy_bootstrap_job(tmp_path, monkeypatch):
    deploy = load_deploy_module()
    monkeypatch.setenv("HOME", str(tmp_path))
    launch_agents = tmp_path / "Library" / "LaunchAgents"
    launch_agents.mkdir(parents=True)
    custom = launch_agents / "work.harqis.deploy.plist"
    contents = """<?xml version="1.0" encoding="UTF-8"?>
<plist version="1.0"><dict>
  <key>Label</key><string>work.harqis.deploy</string>
  <key>ProgramArguments</key><array>
    <string>/usr/bin/true</string>
  </array>
</dict></plist>
"""
    custom.write_text(contents, encoding="utf-8")
    calls: list[list[str]] = []

    def fake_run(command, **kwargs):
        calls.append(command)
        return type("Result", (), {"returncode": 0})()

    monkeypatch.setattr(deploy.subprocess, "run", fake_run)

    deploy._register_launchd({}, argparse.Namespace(), [], load=True)

    assert custom.read_text(encoding="utf-8") == contents
    assert calls == []
