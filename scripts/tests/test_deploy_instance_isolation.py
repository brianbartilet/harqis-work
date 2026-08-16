from __future__ import annotations

import importlib.util
import os
from pathlib import Path
import subprocess
import sys

import pytest


def load_deploy_module():
    path = Path(__file__).resolve().parents[1] / "deploy.py"
    spec = importlib.util.spec_from_file_location("deploy_instance_isolation_test", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_upstream_service_names_and_runtime_paths_remain_compatible(monkeypatch):
    monkeypatch.delenv("HARQIS_INSTANCE", raising=False)
    deploy = load_deploy_module()

    assert deploy._service_label("worker") == "work.harqis.worker"
    assert deploy._systemd_unit_name("worker") == "harqis-worker.service"
    assert deploy.pid_path("worker").parent == deploy.REPO_ROOT / ".run"
    assert deploy.log_path("worker").parent == deploy.REPO_ROOT / "logs"


def test_service_names_and_runtime_paths_are_instance_scoped(monkeypatch):
    monkeypatch.setenv("HARQIS_INSTANCE", "ALAM Tech Labs")
    deploy = load_deploy_module()

    assert deploy._service_label("worker") == "work.harqis.alam-tech-labs.worker"
    assert deploy._systemd_unit_name("worker") == "harqis-alam-tech-labs-worker.service"
    assert deploy.pid_path("worker").parent.parts[-2:] == (".run", "alam-tech-labs")
    assert deploy.log_path("worker").parent.parts[-2:] == ("logs", "alam-tech-labs")


def test_process_filter_rejects_other_checkout(monkeypatch):
    deploy = load_deploy_module()

    class Result:
        stdout = "/opt/harqis-work/.venv/bin/python -m celery worker"
        returncode = 0

    monkeypatch.setattr(deploy.subprocess, "run", lambda *args, **kwargs: Result())

    assert deploy._pid_belongs_to_repo(42) is False


def test_concurrent_deploy_for_same_instance_fails_closed(tmp_path, monkeypatch):
    deploy = load_deploy_module()
    monkeypatch.setattr(deploy, "RUN_DIR", tmp_path / ".run")

    with deploy.deploy_operation_lock():
        with pytest.raises(RuntimeError, match="deploy operation is already running"):
            with deploy.deploy_operation_lock():
                pass


def test_main_resolves_instance_before_acquiring_deploy_lock(tmp_path, monkeypatch):
    deploy = load_deploy_module()
    observed = []
    monkeypatch.setattr(sys, "argv", ["deploy.py", "--down"])
    monkeypatch.setenv("HARQIS_INSTANCE", "pre-test")
    monkeypatch.setattr(deploy, "RUN_DIR", tmp_path / ".run")
    monkeypatch.setattr(deploy, "LOG_DIR", tmp_path / "logs")
    monkeypatch.setattr(deploy, "load_env_into_os", lambda: None)
    monkeypatch.setattr(
        deploy,
        "load_machine_config",
        lambda machine=None: {"role": "host", "env_vars": {}},
    )
    monkeypatch.setattr(
        deploy,
        "machine_env_vars",
        lambda machine: {"HARQIS_INSTANCE": "resolved-instance"},
    )
    monkeypatch.setattr(deploy, "_main", lambda args, machine: observed.append(deploy._run_dir()))

    deploy.main()

    assert observed == [tmp_path / ".run" / "resolved-instance"]


def test_main_preserves_non_lock_runtime_errors(tmp_path, monkeypatch):
    deploy = load_deploy_module()
    monkeypatch.setattr(sys, "argv", ["deploy.py", "--down"])
    monkeypatch.setattr(deploy, "RUN_DIR", tmp_path / ".run")
    monkeypatch.setattr(deploy, "LOG_DIR", tmp_path / "logs")
    monkeypatch.setattr(deploy, "load_env_into_os", lambda: None)
    monkeypatch.setattr(deploy, "load_machine_config", lambda machine=None: {"role": "host"})
    monkeypatch.setattr(deploy, "machine_env_vars", lambda machine: {})
    monkeypatch.setattr(
        deploy,
        "_main",
        lambda args, machine: (_ for _ in ()).throw(RuntimeError("lifecycle failed")),
    )

    with pytest.raises(RuntimeError, match="lifecycle failed"):
        deploy.main()


def test_deploy_bootstraps_without_site_packages():
    deploy_path = Path(__file__).resolve().parents[1] / "deploy.py"

    result = subprocess.run(
        [sys.executable, "-S", str(deploy_path), "--help"],
        cwd=deploy_path.parent.parent,
        env={**os.environ, "PYTHONPATH": ""},
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
