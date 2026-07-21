"""Tests for granular notes-to-Activity-Corpus ingestion."""

from datetime import datetime
from pathlib import Path
import subprocess

from workflows.hfl.tasks import ingest_notes as subject
from workflows.notes.config import NoteRepository


def _run(path: Path, *args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=path, check=True, capture_output=True, text=True,
    ).stdout.strip()


def _repository(tmp_path: Path) -> tuple[NoteRepository, str]:
    checkout = tmp_path / "notes"
    checkout.mkdir()
    _run(checkout, "init", "-b", "master")
    _run(checkout, "config", "user.email", "notes-test@example.invalid")
    _run(checkout, "config", "user.name", "Notes Test")
    (checkout / "old.md").write_text("old\n", encoding="utf-8")
    _run(checkout, "add", ".")
    _run(checkout, "commit", "-m", "baseline")
    baseline = _run(checkout, "rev-parse", "HEAD")
    repository = NoteRepository(
        name="notes", remote="git@github.com:brianbartilet/notes.git",
        branch="master", host_path=checkout, tags=("notes", "dsm"),
        include_globs=(), exclude_globs=("private/**",), max_entries=25,
        max_media=10, max_text_chars=20_000,
    )
    return repository, baseline


def test_collects_granular_text_and_reference_changes(tmp_path):
    repository, baseline = _repository(tmp_path)
    (repository.host_path / "Logs").mkdir()
    (repository.host_path / "Logs" / "today.md").write_text("A useful note\n", encoding="utf-8")
    (repository.host_path / "sheet.xlsx").write_bytes(b"spreadsheet")
    _run(repository.host_path, "add", ".")
    _run(repository.host_path, "commit", "-m", "notes update")

    activity = subject.collect_note_changes(repository, from_commit=baseline)

    assert [(item.path, item.kind) for item in activity["changes"]] == [
        ("Logs/today.md", "text"), ("sheet.xlsx", "reference")
    ]
    assert activity["changes"][0].content == "A useful note\n"


def test_required_tags_include_repo_and_core_topic(tmp_path):
    repository, _ = _repository(tmp_path)
    tags = subject._entry_tags(repository, {"core_topic": "Deep Work", "tags": ["idea"]})
    assert tags[:4] == ["notes", "dsm", "repo-notes", "deep-work"]


def test_first_activation_sets_baseline_without_writing(monkeypatch, tmp_path):
    repository, _ = _repository(tmp_path)
    head = _run(repository.host_path, "rev-parse", "HEAD")
    stored = []
    monkeypatch.setattr(subject, "get_note_repositories", lambda: {"notes": repository})
    monkeypatch.setattr(subject, "recent_pull_succeeded", lambda *a, **k: True)
    monkeypatch.setattr(subject, "load_ingest_cursor", lambda name: "")
    monkeypatch.setattr(subject, "store_ingest_cursor", lambda name, value: stored.append((name, value)))

    result = subject.ingest_notes_activity(repository_names=["notes"], synthesize=False)

    assert result["entries_written"] == 0
    assert result["repositories"]["notes"]["skipped"] == "baseline initialized"
    assert stored == [("notes", head)]


def test_failed_write_does_not_advance_cursor(monkeypatch, tmp_path):
    repository, baseline = _repository(tmp_path)
    change = subject.NoteChange(
        status="M", path="old.md", kind="text", content="new",
        changed_at=datetime(2026, 7, 21, 12, 0),
    )
    stored = []
    monkeypatch.setattr(subject, "get_note_repositories", lambda: {"notes": repository})
    monkeypatch.setattr(subject, "recent_pull_succeeded", lambda *a, **k: True)
    monkeypatch.setattr(subject, "load_ingest_cursor", lambda name: baseline)
    monkeypatch.setattr(subject, "collect_note_changes", lambda *a, **k: {"changes": [change]})
    monkeypatch.setattr(subject, "distill_note_change", lambda *a, **k: {"skip": False})
    monkeypatch.setattr(subject, "_write_entry", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("write failed")))
    monkeypatch.setattr(subject, "store_ingest_cursor", lambda *a: stored.append(a))
    monkeypatch.setattr(subject, "_head", lambda repo: "new-head")

    result = subject.ingest_notes_activity(repository_names=["notes"], synthesize=False)

    assert result["repositories"]["notes"]["cursor_advanced"] is False
    assert stored == []
