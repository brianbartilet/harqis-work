"""Parse generated units with real systemd when available; never start a service."""
from __future__ import annotations

import importlib.util
from pathlib import Path
import shutil
import subprocess
from types import SimpleNamespace

import pytest


@pytest.mark.skipif(shutil.which("systemd-analyze") is None, reason="systemd parser unavailable")
def test_generated_systemd_unit_passes_native_parser(tmp_path, monkeypatch):
    path = Path(__file__).resolve().parents[1] / "deploy.py"
    spec = importlib.util.spec_from_file_location("deploy_systemd_syntax", path)
    assert spec is not None and spec.loader is not None
    deploy = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(deploy)
    root = tmp_path / "server space % dollar$"
    root.mkdir()
    logs = root / "logs"
    logs.mkdir()
    unit = tmp_path / "harqis-worker.service"
    monkeypatch.setattr(deploy, "IS_MAC", False)
    monkeypatch.setattr(deploy, "IS_LIN", True)
    monkeypatch.setattr(deploy, "IS_WIN", False)
    monkeypatch.setattr(deploy, "REPO_ROOT", root)
    monkeypatch.setattr(deploy, "LOG_DIR", logs)
    monkeypatch.setattr(deploy, "_systemd_unit_path", lambda service: unit)
    args = deploy.build_parser().parse_args(["--queues", "default,hfl"])
    with monkeypatch.context() as context:
        context.setattr(deploy.subprocess, "run", lambda *a, **kw: SimpleNamespace(returncode=0))
        deploy._register_systemd({"env_vars": {"EXAMPLE_PATH": "spaces % dollar$"}}, args, ["worker"], activate=False)
    parser = shutil.which("systemd-analyze")
    assert parser is not None
    result = subprocess.run([parser, "verify", str(unit)],
                            capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stdout + result.stderr
    # systemd may ignore malformed directives with warnings but still exit 0.
    assert not result.stderr.strip(), result.stderr
