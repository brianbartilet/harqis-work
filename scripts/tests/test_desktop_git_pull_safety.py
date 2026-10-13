"""Offline task regressions: real Git, inert hooks, no Celery/app services."""
from __future__ import annotations

import importlib.util
import os
from pathlib import Path
import subprocess
import sys
from types import ModuleType, SimpleNamespace

import pytest


@pytest.fixture
def commands(monkeypatch):
    # Load the exact sibling source, not an installed/runtime workflows package.
    # Stub only unrelated integrations and task/logging decorators: the complete
    # production function and its subprocess calls execute unchanged.
    def identity(*args, **kwargs):
        return lambda function: function

    dependencies = {
        "core.apps.sprout.app.celery": {"SPROUT": SimpleNamespace(task=identity)},
        "core.apps.es_logging.app.elasticsearch": {"log_result": identity},
        "core.utilities.files": {"copy_files_any": None},
        "apps.rainmeter.references.helpers.settings": {"set_rainmeter_always_on_top": None},
        "apps.rainmeter.references.helpers.config_builder": {"_refresh_app": None},
        "apps.desktop.helpers.feed": {"feed": identity},
        "apps.apps_config": {"CONFIG_MANAGER": None},
        "workflows.dumps.config": {"load_merged_config": None, "resolve_local_machine_name": None},
    }
    for name, attributes in dependencies.items():
        module = ModuleType(name)
        module.__dict__.update(attributes)
        monkeypatch.setitem(sys.modules, name, module)
    root = Path(__file__).resolve().parents[2]
    source = root / "workflows" / "desktop" / "tasks" / "commands.py"
    spec = importlib.util.spec_from_file_location("desktop_commands_pull_test", source)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    assert module.REPO_ROOT == root
    return module


@pytest.fixture
def repos(tmp_path, monkeypatch):
    # Never inherit host hooks, identities, signing, Git directory overrides or
    # network transports. Every repo and configuration file is disposable.
    for key in list(os.environ):
        if key.startswith("GIT_"):
            monkeypatch.delenv(key)
    home = tmp_path / "home"
    home.mkdir()
    for key, value in {
        "HOME": str(home), "XDG_CONFIG_HOME": str(home),
        "GIT_CONFIG_NOSYSTEM": "1", "GIT_CONFIG_GLOBAL": os.devnull,
        "GIT_ALLOW_PROTOCOL": "file", "GIT_TERMINAL_PROMPT": "0",
        "GIT_AUTHOR_NAME": "Test", "GIT_COMMITTER_NAME": "Test",
        "GIT_AUTHOR_EMAIL": "test@example.invalid",
        "GIT_COMMITTER_EMAIL": "test@example.invalid",
        "GIT_EDITOR": "true", "LC_ALL": "C",
    }.items():
        monkeypatch.setenv(key, value)

    def git(cwd, *args, check=True):
        return subprocess.run(
            ["git", *args], cwd=cwd, capture_output=True, text=True,
            check=check, timeout=15,
        )

    origin, seed, local = (tmp_path / name for name in ("origin.git", "seed", "local"))
    git(tmp_path, "init", "--bare", "--initial-branch=main", str(origin))
    git(tmp_path, "clone", str(origin), str(seed))
    (seed / "tracked.txt").write_text("initial\n")
    git(seed, "add", ".")
    git(seed, "commit", "-m", "initial")
    git(seed, "push", "origin", "main")
    git(tmp_path, "clone", str(origin), str(local))

    def advance():
        (seed / "tracked.txt").write_text("upstream\n")
        git(seed, "commit", "-am", "upstream")
        git(seed, "push", "origin", "main")
        return git(seed, "rev-parse", "HEAD").stdout.strip()

    return SimpleNamespace(local=local, seed=seed, git=git, advance=advance)


@pytest.mark.parametrize("custom_hooks", [False, True])
def test_fast_forward_does_not_run_or_reconfigure_hooks(commands, repos, monkeypatch, custom_hooks):
    local, git = repos.local, repos.git
    hooks = local / ("custom-hooks" if custom_hooks else ".git/hooks")
    hooks.mkdir(exist_ok=True)
    if custom_hooks:
        git(local, "config", "core.hooksPath", str(hooks))
    hook = hooks / "post-merge"
    hook.write_text("#!/bin/sh\nprintf 'restart requested\\n' > hook-fired\n")
    hook.chmod(0o755)
    config_before = (local / ".git/config").read_bytes()
    expected = repos.advance()
    monkeypatch.setattr(commands, "REPO_ROOT", local)

    assert commands.git_pull_on_paths() == str(local)

    assert git(local, "rev-parse", "HEAD").stdout.strip() == expected
    assert not (local / "hook-fired").exists()
    assert (local / ".git/config").read_bytes() == config_before
    # Prove the same hook is still enabled for an explicit non-task Git action.
    git(local, "reset", "--hard", "HEAD~1")
    git(local, "merge", "--ff-only", "origin/main")
    assert (local / "hook-fired").read_text() == "restart requested\n"


@pytest.mark.parametrize("rebase", ["false", "true"])
def test_divergence_is_refused_even_with_pull_preferences(commands, repos, monkeypatch, capsys, rebase):
    local, git = repos.local, repos.git
    git(local, "config", "pull.rebase", rebase)
    git(local, "config", "pull.ff", "false")
    (local / "local.txt").write_text("local commit\n")
    git(local, "add", "local.txt")
    git(local, "commit", "-m", "local")
    before = git(local, "rev-parse", "HEAD").stdout
    repos.advance()
    monkeypatch.setattr(commands, "REPO_ROOT", local)

    assert commands.git_pull_on_paths() == str(local)

    assert git(local, "rev-parse", "HEAD").stdout == before
    assert "Not possible to fast-forward" in capsys.readouterr().out
    assert (local / "local.txt").read_text() == "local commit\n"
    assert not (local / ".git/MERGE_HEAD").exists()
    assert not (local / ".git/rebase-merge").exists()
    assert not (local / ".git/rebase-apply").exists()


def test_up_to_date_pull_preserves_return_and_output(commands, repos, monkeypatch, capsys):
    before = repos.git(repos.local, "rev-parse", "HEAD").stdout
    monkeypatch.setattr(commands, "REPO_ROOT", repos.local)
    assert commands.git_pull_on_paths() == str(repos.local)
    assert "Already up to date" in capsys.readouterr().out
    assert repos.git(repos.local, "rev-parse", "HEAD").stdout == before


def test_fetch_failure_is_still_logged(commands, repos, monkeypatch, capsys):
    repos.git(repos.local, "remote", "set-url", "origin", str(repos.local / "missing.git"))
    before = repos.git(repos.local, "rev-parse", "HEAD").stdout
    monkeypatch.setattr(commands, "REPO_ROOT", repos.local)
    assert commands.git_pull_on_paths() == str(repos.local)
    assert "does not appear to be a git repository" in capsys.readouterr().out
    assert repos.git(repos.local, "rev-parse", "HEAD").stdout == before


def test_conflicting_local_edits_are_preserved(commands, repos, monkeypatch, capsys):
    before = repos.git(repos.local, "rev-parse", "HEAD").stdout
    repos.advance()
    (repos.local / "tracked.txt").write_text("uncommitted work\n")
    monkeypatch.setattr(commands, "REPO_ROOT", repos.local)
    assert commands.git_pull_on_paths() == str(repos.local)
    assert "would be overwritten" in capsys.readouterr().out
    assert repos.git(repos.local, "rev-parse", "HEAD").stdout == before
    assert (repos.local / "tracked.txt").read_text() == "uncommitted work\n"


def test_subprocess_failure_is_still_logged(commands, tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(commands, "REPO_ROOT", tmp_path)

    def fail(*args, **kwargs):
        raise OSError("git unavailable")

    monkeypatch.setattr(commands, "subprocess", SimpleNamespace(run=fail, PIPE=subprocess.PIPE))
    assert commands.git_pull_on_paths() == str(tmp_path)
    assert "git unavailable" in capsys.readouterr().out


def test_missing_path_never_invokes_git(commands, tmp_path, monkeypatch):
    missing = tmp_path / "absent"
    monkeypatch.setattr(commands, "REPO_ROOT", missing)

    def unexpected(*args, **kwargs):
        pytest.fail("Git must not run for a missing path")

    monkeypatch.setattr(commands, "subprocess", SimpleNamespace(run=unexpected, PIPE=subprocess.PIPE))
    assert commands.git_pull_on_paths() == str(missing)
