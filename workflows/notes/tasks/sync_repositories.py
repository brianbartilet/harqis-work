"""Daily Git synchronization for configured note repositories.

At 22:30 every ``default_broadcast`` subscriber inspects only the note
repositories bound to that machine, commits local changes, and pushes without
force or automatic conflict resolution. At 22:40 the HARQIS host clones missing
repositories or performs a clean fast-forward-only update, then records the
exact head consumed by the HFL ingest task.
"""

from __future__ import annotations

import os
import subprocess
from datetime import datetime
from pathlib import Path
from typing import Any

from core.apps.sprout.app.celery import SPROUT
from core.apps.es_logging.app.elasticsearch import log_result
from core.utilities.logging.custom_logger import create_logger

from workflows.notes.config import (
    NoteRepository,
    get_local_note_repositories,
    get_note_repositories,
    is_harqis_host,
)
from workflows.notes.state import record_pull_status

_log = create_logger("notes.sync_repositories")


def _git(args: list[str], *, cwd: Path | None = None, timeout: int = 120) -> subprocess.CompletedProcess:
    env = {**os.environ, "GIT_TERMINAL_PROMPT": "0"}
    return subprocess.run(
        ["git", *args], cwd=str(cwd) if cwd else None, env=env,
        timeout=timeout, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        text=True,
    )


def _detail(result: subprocess.CompletedProcess) -> str:
    return (result.stderr or result.stdout or "").strip().replace("\n", " ")[:300]


def _head(path: Path) -> str:
    result = _git(["rev-parse", "HEAD"], cwd=path)
    return result.stdout.strip() if result.returncode == 0 else ""


def push_note_repository(repository: NoteRepository, source_path: Path) -> dict[str, Any]:
    """Commit and push one source checkout without pulling or force-pushing."""
    if not source_path.is_dir() or not (source_path / ".git").exists():
        return {"status": "skipped", "detail": "not a git repository"}

    branch = _git(["branch", "--show-current"], cwd=source_path)
    if branch.returncode != 0 or branch.stdout.strip() != repository.branch:
        return {"status": "error", "detail": f"expected branch {repository.branch}"}

    staged = _git(["add", "-A"], cwd=source_path)
    if staged.returncode != 0:
        return {"status": "error", "detail": f"git add failed: {_detail(staged)}"}

    changed = _git(["diff", "--cached", "--name-only"], cwd=source_path)
    created_commit = False
    if changed.stdout.strip():
        stamp = datetime.now().strftime("%Y-%m-%d %H:%M")
        commit = _git(["commit", "-m", f"chore(notes): sync {stamp}"], cwd=source_path)
        if commit.returncode != 0:
            return {"status": "error", "detail": f"commit failed: {_detail(commit)}"}
        created_commit = True

    push = _git(
        ["push", repository.remote_name, repository.branch],
        cwd=source_path, timeout=180,
    )
    if push.returncode != 0:
        return {"status": "error", "detail": f"push failed: {_detail(push)}", "head": _head(source_path)}
    return {
        "status": "pushed" if created_commit else "no-changes",
        "detail": "committed and pushed" if created_commit else "remote already current",
        "head": _head(source_path),
    }


def pull_note_repository(repository: NoteRepository) -> dict[str, Any]:
    """Clone or fast-forward one clean host checkout."""
    path = repository.host_path
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        clone = _git([
            "clone", "--branch", repository.branch, "--single-branch",
            repository.remote, str(path),
        ], timeout=300)
        if clone.returncode != 0:
            return {"status": "error", "detail": f"clone failed: {_detail(clone)}"}
        return {"status": "cloned", "detail": "repository cloned", "head": _head(path)}

    if not (path / ".git").exists():
        return {"status": "error", "detail": "host path exists but is not a git repository"}

    dirty = _git(["status", "--porcelain"], cwd=path)
    if dirty.returncode != 0 or dirty.stdout.strip():
        return {"status": "error", "detail": "host checkout is not clean", "head": _head(path)}

    branch = _git(["branch", "--show-current"], cwd=path)
    if branch.returncode != 0 or branch.stdout.strip() != repository.branch:
        return {"status": "error", "detail": f"expected branch {repository.branch}", "head": _head(path)}

    fetch = _git(["fetch", repository.remote_name, repository.branch], cwd=path, timeout=180)
    if fetch.returncode != 0:
        return {"status": "error", "detail": f"fetch failed: {_detail(fetch)}", "head": _head(path)}
    before = _head(path)
    merge = _git([
        "merge", "--ff-only", f"{repository.remote_name}/{repository.branch}"
    ], cwd=path, timeout=180)
    if merge.returncode != 0:
        return {"status": "error", "detail": f"fast-forward failed: {_detail(merge)}", "head": before}
    after = _head(path)
    return {
        "status": "updated" if before != after else "no-changes",
        "detail": "fast-forwarded" if before != after else "host already current",
        "head": after,
    }


@log_result()
@SPROUT.task(name="workflows.notes.tasks.sync_repositories.broadcast_push_note_repositories")
def broadcast_push_note_repositories(**kwargs) -> dict[str, Any]:
    """Commit and push note repositories bound to this worker's machine key."""
    del kwargs
    bindings = get_local_note_repositories()
    if not bindings:
        return {"skipped": "no note repositories configured", "repositories": {}}
    results: dict[str, dict[str, Any]] = {}
    for binding in bindings:
        result = push_note_repository(binding.definition, binding.source_path)
        results[binding.definition.name] = result
        _log.info("notes push %s: %s", binding.definition.name, result["status"])
    return {"repositories": results, "ok": all(r["status"] != "error" for r in results.values())}


@log_result()
@SPROUT.task(name="workflows.notes.tasks.sync_repositories.pull_note_repositories")
def pull_note_repositories(**kwargs) -> dict[str, Any]:
    """Clone/pull all configured repositories on the canonical HARQIS host."""
    del kwargs
    if not is_harqis_host():
        return {"skipped": "not harqis host", "repositories": {}}
    repositories = get_note_repositories()
    if not repositories:
        return {"skipped": "no note repositories configured", "repositories": {}}
    results: dict[str, dict[str, Any]] = {}
    for name, repository in repositories.items():
        result = pull_note_repository(repository)
        results[name] = result
        success = result["status"] != "error" and bool(result.get("head"))
        record_pull_status(
            name, success=success, head=str(result.get("head", "")),
            detail=str(result.get("detail", "")),
        )
        _log.info("notes pull %s: %s", name, result["status"])
    return {"repositories": results, "ok": all(r["status"] != "error" for r in results.values())}
