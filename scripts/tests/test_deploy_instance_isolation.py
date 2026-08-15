from __future__ import annotations

import importlib.util
from pathlib import Path


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
