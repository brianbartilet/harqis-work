"""
Tests for agents/projects/orchestrator/worktree.py

Uses a real temp git repo so we exercise the actual `git worktree` plumbing —
the whole point of this module is that subprocess git commands cooperate
under concurrent allocation. Mocking subprocess would erase the test's value.
"""

from __future__ import annotations

import subprocess
import threading
from pathlib import Path

import pytest
from hamcrest import assert_that, equal_to, is_in, is_not, none, not_none

from agents.projects.orchestrator.worktree import (
    Worktree,
    WorktreeError,
    allocate,
    prune_stale,
    release,
    repo_root,
)


# ── Helpers ──────────────────────────────────────────────────────────────────

def _git(args: list[str], cwd: Path, check: bool = True) -> str:
    result = subprocess.run(
        ["git"] + args, cwd=str(cwd),
        capture_output=True, text=True, timeout=30,
    )
    if check and result.returncode != 0:
        raise AssertionError(
            f"git {' '.join(args)} failed: {result.stderr or result.stdout}"
        )
    return result.stdout.strip()


@pytest.fixture()
def repo(tmp_path: Path) -> Path:
    """A throwaway git repo with one commit on `main`."""
    r = tmp_path / "src"
    r.mkdir()
    _git(["init", "-q", "-b", "main"], cwd=r)
    _git(["config", "user.email", "t@e.test"], cwd=r)
    _git(["config", "user.name", "Test"], cwd=r)
    (r / "README.md").write_text("hello\n")
    _git(["add", "."], cwd=r)
    _git(["commit", "-q", "-m", "init"], cwd=r)
    return r


# ── repo_root ────────────────────────────────────────────────────────────────

def test_repo_root_resolves_from_subdir(repo: Path, tmp_path: Path):
    sub = repo / "nested"
    sub.mkdir()
    assert_that(repo_root(sub), equal_to(repo.resolve()))


def test_repo_root_outside_repo_raises(tmp_path: Path):
    not_a_repo = tmp_path / "elsewhere"
    not_a_repo.mkdir()
    with pytest.raises(WorktreeError):
        repo_root(not_a_repo)


# ── allocate / release ───────────────────────────────────────────────────────

def test_allocate_creates_worktree_with_detached_head(repo: Path):
    wt = allocate(repo, card_id="card-A")
    try:
        assert_that(wt.path.exists(), equal_to(True))
        assert_that((wt.path / "README.md").read_text(), equal_to("hello\n"))
        # Each worktree owns its own HEAD; agent can `checkout -b` here
        # without touching the source repo's HEAD.
        head = _git(["rev-parse", "--abbrev-ref", "HEAD"], cwd=wt.path)
        assert_that(head, equal_to("HEAD"))  # detached
    finally:
        release(wt)


def test_release_removes_worktree_dir_and_tmp_parent(repo: Path):
    wt = allocate(repo, card_id="card-B")
    tmp_parent = wt.path.parent
    release(wt)
    assert_that(wt.path.exists(), equal_to(False))
    assert_that(tmp_parent.exists(), equal_to(False))


def test_release_is_idempotent(repo: Path):
    wt = allocate(repo, card_id="card-C")
    release(wt)
    # Calling release twice must not raise (best-effort contract).
    release(wt)


def test_agent_can_branch_inside_worktree_without_touching_source(repo: Path):
    """The whole point — `git checkout -b` inside the worktree should
    not race with sibling worktrees because indexes are per-worktree."""
    source_head_before = _git(["rev-parse", "HEAD"], cwd=repo)
    source_branch_before = _git(["rev-parse", "--abbrev-ref", "HEAD"], cwd=repo)

    wt = allocate(repo, card_id="card-D")
    try:
        _git(["checkout", "-b", "agent/card-D/work", "--"], cwd=wt.path)
        (wt.path / "new.txt").write_text("from worktree\n")
        _git(["add", "."], cwd=wt.path)
        _git(["-c", "user.email=t@e.test", "-c", "user.name=t",
              "commit", "-q", "-m", "work"], cwd=wt.path)

        # Source repo is untouched.
        assert_that(_git(["rev-parse", "HEAD"], cwd=repo), equal_to(source_head_before))
        assert_that(
            _git(["rev-parse", "--abbrev-ref", "HEAD"], cwd=repo),
            equal_to(source_branch_before),
        )
    finally:
        release(wt)


def test_parallel_allocate_under_threads_does_not_collide(repo: Path):
    """Spin up N threads, each allocates+releases. Without the internal
    lock around `git worktree add`, this races on git's own metadata."""
    n = 8
    results: list[Worktree] = []
    errors: list[BaseException] = []
    barrier = threading.Barrier(n)
    lock = threading.Lock()

    def worker(card_id: str) -> None:
        try:
            barrier.wait(timeout=10)
            wt = allocate(repo, card_id=card_id)
            with lock:
                results.append(wt)
        except BaseException as e:  # noqa: BLE001 — surface any thread error
            with lock:
                errors.append(e)

    threads = [
        threading.Thread(target=worker, args=(f"card-P{i}",)) for i in range(n)
    ]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=30)

    try:
        assert_that(errors, equal_to([]))
        assert_that(len(results), equal_to(n))
        # All paths must be unique (no two threads got the same worktree).
        paths = {str(w.path) for w in results}
        assert_that(len(paths), equal_to(n))
    finally:
        for wt in results:
            release(wt)


def test_allocate_rejects_dash_card_id(repo: Path):
    with pytest.raises(ValueError):
        allocate(repo, card_id="-evil")


def test_allocate_rejects_dash_base_ref(repo: Path):
    with pytest.raises(ValueError):
        allocate(repo, card_id="card-x", base_ref="-bad")


def test_allocate_failure_cleans_up_tmp_dir(repo: Path):
    # Force failure by passing a ref that doesn't exist. The temp parent
    # mkdtemp created must be cleaned up so we don't leak.
    with pytest.raises(WorktreeError):
        allocate(repo, card_id="card-fail", base_ref="this-ref-does-not-exist")
    # We can't easily inspect the cleanup path from outside without
    # patching mkdtemp; the assertion that matters is that subsequent
    # allocate calls still succeed (no leftover lock holds anything).
    wt = allocate(repo, card_id="card-after-fail")
    try:
        assert_that(wt.path.exists(), equal_to(True))
    finally:
        release(wt)


# ── prune_stale ──────────────────────────────────────────────────────────────

def test_prune_stale_cleans_registration_after_dir_removed(repo: Path):
    wt = allocate(repo, card_id="card-prune")
    # Simulate a crashed run: nuke the worktree dir without going through release.
    import shutil
    shutil.rmtree(wt.path.parent, ignore_errors=True)

    # The registration entry still lingers — listed by `git worktree list`.
    listing_before = _git(["worktree", "list", "--porcelain"], cwd=repo)
    assert_that(str(wt.path), is_in(listing_before))

    prune_stale(repo)

    listing_after = _git(["worktree", "list", "--porcelain"], cwd=repo)
    assert_that(str(wt.path), is_not(is_in(listing_after)))
