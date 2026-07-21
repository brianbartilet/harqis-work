"""Regression tests for safe repository-backed notes synchronization."""

from pathlib import Path
import subprocess

from workflows.notes.config import NoteRepository
from workflows.notes.tasks.sync_repositories import (
    pull_note_repository,
    push_note_repository,
)


def _run(path: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", *args], cwd=path, check=True, capture_output=True, text=True,
    )
    return result.stdout.strip()


def _definition(remote: Path, host_path: Path) -> NoteRepository:
    return NoteRepository(
        name="notes", remote=str(remote), branch="master",
        host_path=host_path, tags=("notes", "dsm"), include_globs=(),
        exclude_globs=(".git/**",), max_entries=25, max_media=10,
        max_text_chars=20_000, max_topics_per_note=4,
    )


def _source_and_remote(tmp_path: Path) -> tuple[Path, Path]:
    remote = tmp_path / "notes.git"
    source = tmp_path / "source"
    remote.mkdir()
    source.mkdir()
    _run(remote, "init", "--bare")
    _run(source, "init", "-b", "master")
    _run(source, "config", "user.email", "notes-test@example.invalid")
    _run(source, "config", "user.name", "Notes Test")
    _run(source, "remote", "add", "origin", str(remote))
    (source / "README.md").write_text("first\n", encoding="utf-8")
    _run(source, "add", "README.md")
    _run(source, "commit", "-m", "initial")
    _run(source, "push", "-u", "origin", "master")
    return source, remote


def test_push_commits_and_pushes_without_force(tmp_path):
    source, remote = _source_and_remote(tmp_path)
    definition = _definition(remote, tmp_path / "host")
    (source / "daily.md").write_text("changed note\n", encoding="utf-8")

    result = push_note_repository(definition, source)

    assert result["status"] == "pushed"
    assert _run(source, "status", "--porcelain") == ""
    assert _run(remote, "rev-parse", "refs/heads/master") == result["head"]


def test_pull_clones_then_refuses_a_dirty_host_checkout(tmp_path):
    _, remote = _source_and_remote(tmp_path)
    definition = _definition(remote, tmp_path / "host")

    assert pull_note_repository(definition)["status"] == "cloned"
    (definition.host_path / "README.md").write_text("host edit\n", encoding="utf-8")

    result = pull_note_repository(definition)

    assert result["status"] == "error"
    assert result["detail"] == "host checkout is not clean"
