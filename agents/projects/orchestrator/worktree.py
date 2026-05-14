"""
Per-card git worktree isolation for parallel agent dispatch.

Background: parallel agents that all operate on the same working tree race
on ``.git/index.lock`` during ``git checkout -b``. Each ``git worktree``
gets its own working dir + index + HEAD while sharing the object database,
which removes the lock contention without paying for a full clone.

Lifecycle:
    base = repo_root()
    wt = allocate(base, card_id="abc123")
    try:
        # agent runs against wt.path; creates its own branch with
        # `git checkout -b agent/abc123/...` (now safe — separate index)
        ...
    finally:
        release(wt)

Concurrency: ``git worktree add`` and ``git worktree remove`` both briefly
touch the source repo's metadata, so this module serializes those calls
with a process-wide lock. The lock is short-lived (metadata only); it does
not block the agents' actual work inside the worktree.
"""

from __future__ import annotations

import logging
import os
import shutil
import subprocess
import tempfile
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

_WORKTREE_OP_LOCK = threading.Lock()
_TMP_PREFIX = "kanban-agent-"


class WorktreeError(RuntimeError):
    """Raised when worktree allocation or release fails."""


@dataclass
class Worktree:
    path: Path
    base_repo: Path
    card_id: str


def repo_root(start: Optional[Path] = None) -> Path:
    """Resolve the top-level directory of the git repo containing ``start``.

    Defaults to ``os.getcwd()``. Raises WorktreeError if not in a repo.
    """
    cwd = str(start) if start else os.getcwd()
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],
            cwd=cwd, capture_output=True, text=True, timeout=10,
        )
    except (OSError, subprocess.TimeoutExpired) as e:
        raise WorktreeError(f"git rev-parse failed in {cwd}: {e}") from e
    if result.returncode != 0:
        raise WorktreeError(
            f"{cwd} is not inside a git repo: {result.stderr.strip()}"
        )
    return Path(result.stdout.strip())


def allocate(
    base_repo: Path,
    card_id: str,
    *,
    base_ref: str = "HEAD",
) -> Worktree:
    """Create a detached-HEAD worktree off ``base_ref`` for one card.

    The agent is expected to run ``git checkout -b agent/<card_id>/...``
    inside the worktree once it has chosen a slug. Because each worktree
    has its own index, this no longer races with sibling agents.

    ``base_ref`` defaults to HEAD (whatever the orchestrator has checked
    out). Set to ``main`` or ``origin/main`` when you want to force a
    clean starting point regardless of the orchestrator's branch.
    """
    if not card_id or card_id.startswith("-"):
        raise ValueError(f"Invalid card_id for worktree: {card_id!r}")
    if not base_ref or base_ref.startswith("-"):
        raise ValueError(f"Invalid base_ref for worktree: {base_ref!r}")

    tmp_parent = Path(tempfile.mkdtemp(prefix=f"{_TMP_PREFIX}{card_id}-"))
    # mkdtemp creates the parent; `git worktree add` refuses an existing
    # non-empty path, so use a child.
    worktree_path = tmp_parent / "repo"

    with _WORKTREE_OP_LOCK:
        result = subprocess.run(
            [
                "git", "worktree", "add", "--detach",
                str(worktree_path), base_ref, "--",
            ],
            cwd=str(base_repo),
            capture_output=True, text=True, timeout=60,
        )

    if result.returncode != 0:
        shutil.rmtree(tmp_parent, ignore_errors=True)
        raise WorktreeError(
            f"git worktree add failed for card {card_id}: "
            f"{(result.stderr or result.stdout).strip()}"
        )

    logger.info(
        "Allocated worktree for card %s at %s (base_ref=%s)",
        card_id, worktree_path, base_ref,
    )
    return Worktree(path=worktree_path, base_repo=base_repo, card_id=card_id)


def release(worktree: Worktree) -> None:
    """Tear down a worktree. Best-effort: never raises.

    The branch ref the agent created inside the worktree is *not* deleted
    — if the agent pushed it, future inspection of the branch via the
    remote remains possible. Unpushed local commits become unreachable
    and will be garbage-collected eventually.
    """
    if not worktree.path.exists():
        logger.debug(
            "Worktree for card %s at %s already gone — skipping release",
            worktree.card_id, worktree.path,
        )
        _cleanup_tmp_parent(worktree.path)
        return

    with _WORKTREE_OP_LOCK:
        result = subprocess.run(
            [
                "git", "worktree", "remove", "--force",
                str(worktree.path), "--",
            ],
            cwd=str(worktree.base_repo),
            capture_output=True, text=True, timeout=60,
        )

    if result.returncode != 0:
        logger.warning(
            "git worktree remove failed for card %s at %s: %s",
            worktree.card_id, worktree.path,
            (result.stderr or result.stdout).strip(),
        )

    _cleanup_tmp_parent(worktree.path)


def prune_stale(base_repo: Path) -> None:
    """Drop registration entries for worktrees whose dirs have vanished.

    Cheap and idempotent. Safe to call on orchestrator startup to clean
    up after prior crashes — does not touch live worktrees.
    """
    with _WORKTREE_OP_LOCK:
        result = subprocess.run(
            ["git", "worktree", "prune"],
            cwd=str(base_repo),
            capture_output=True, text=True, timeout=30,
        )
    if result.returncode != 0:
        logger.warning(
            "git worktree prune failed in %s: %s",
            base_repo, (result.stderr or result.stdout).strip(),
        )


def _cleanup_tmp_parent(worktree_path: Path) -> None:
    parent = worktree_path.parent
    if parent.name.startswith(_TMP_PREFIX):
        shutil.rmtree(parent, ignore_errors=True)
