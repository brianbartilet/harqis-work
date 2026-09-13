"""Regression coverage for the scheduled test runner; never run live workflows."""
import os
import subprocess
import sys

import pytest

from scripts import launch
from scripts.agents.testing import run_test_suite as suite


@pytest.fixture
def isolated_launcher(monkeypatch):
    # Exercise the real bootstrap without loading credentials or machine overrides.
    monkeypatch.setattr(launch, "load_env_file", lambda: {"RUNNER_APPS": "loaded"})
    monkeypatch.setattr(launch, "_machine_env_vars", lambda: {"RUNNER_MACHINE": "loaded"})
    monkeypatch.setattr(os, "environ", os.environ.copy())
    monkeypatch.setattr(sys, "path", sys.path.copy())
    monkeypatch.chdir(suite.REPO_ROOT)
    monkeypatch.delenv("WORKFLOW_CONFIG", raising=False)
    monkeypatch.delenv("PYTHONPATH", raising=False)


def test_pytest_child_receives_launcher_environment(monkeypatch, isolated_launcher):
    seen = {}

    def run(cmd, **kwargs):
        seen.update(kwargs.get("env", os.environ))
        assert cmd[:3] == [sys.executable, "-m", "pytest"]
        assert kwargs["cwd"] == suite.REPO_ROOT
        return subprocess.CompletedProcess(cmd, 0, "", "")

    monkeypatch.setattr(suite.subprocess, "run", run)
    result = suite.TestRunner().run_pytest(["--collect-only"])
    assert result["passed"]
    assert seen.get("WORKFLOW_CONFIG") == "workflows.config"
    assert seen.get("RUNNER_APPS") == "loaded"
    assert seen.get("RUNNER_MACHINE") == "loaded"
    assert str(suite.REPO_ROOT) in seen["PYTHONPATH"].split(os.pathsep)
    assert str(suite.REPO_ROOT / "scripts") in seen["PYTHONPATH"].split(os.pathsep)


@pytest.mark.parametrize("failure", [
    subprocess.TimeoutExpired("pytest", 120, output=b"partial output\n", stderr=b"partial error\n"),
    OSError("cannot launch pytest"),
])
def test_quick_failure_keeps_evidence_and_saves_json(monkeypatch, isolated_launcher, tmp_path, capsys, failure):
    def run(*args, **kwargs):
        raise failure

    monkeypatch.setattr(suite.subprocess, "run", run)
    runner = suite.TestRunner()
    assert runner.run_quick() is False
    result = runner.results["tests"][0]
    assert result["stdout_lines"] >= 0
    assert result["stderr_lines"] >= 0
    assert result["error"]
    assert result["counts_complete"] is False
    if isinstance(failure, subprocess.TimeoutExpired):
        assert result["stdout"] == "partial output\n"
        assert result["stderr"] == "partial error\n"
        assert "partial error" in capsys.readouterr().out
    else:
        assert "cannot launch pytest" in capsys.readouterr().out
    import json
    saved = json.loads(runner.save_results(tmp_path / "result.json").read_text())
    assert saved["tests"][0] == result


def test_real_pytest_outcomes_not_suite_counts(isolated_launcher, tmp_path, capsys):
    test_file = tmp_path / "test_outcomes.py"
    test_file.write_text(
        "import pytest\n"
        "def test_pass(): pass\n"
        "def test_fail(): assert False, 'regression failure evidence'\n"
        "@pytest.mark.skip(reason='intentional')\n"
        "def test_skip(): pass\n"
        "@pytest.fixture\n"
        "def broken(): raise RuntimeError('setup evidence')\n"
        "def test_error(broken): pass\n"
    )
    runner = suite.TestRunner()
    result = runner.run_pytest([str(test_file), "-q", "--tb=short", "-p", "no:cacheprovider"])
    assert not result["passed"]
    assert result["counts"] == dict(passed=1, failed=1, skipped=1, errors=1, xfailed=0, xpassed=0, deselected=0)
    assert result["counts_complete"] is True
    assert runner.results["summary"] == result["counts"]
    assert "regression failure evidence" in result["stdout"]
    assert "setup evidence" in capsys.readouterr().out


def test_collection_error_counts_zero_executed(isolated_launcher, tmp_path):
    test_file = tmp_path / "test_collection.py"
    test_file.write_text("raise ImportError('intentional collection error')\n")
    result = suite.TestRunner().run_pytest([str(test_file), "-q", "-p", "no:cacheprovider"])
    assert result["counts"]["errors"] == 1
    assert result["counts"]["passed"] == result["counts"]["failed"] == 0
    assert result["counts_complete"] is True
