"""Tests for granular notes-to-Activity-Corpus ingestion."""

from dataclasses import replace
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
        max_media=10, max_text_chars=20_000, max_topics_per_note=4,
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


def test_normalizes_natural_topic_segments_with_line_bounds(tmp_path):
    repository, _ = _repository(tmp_path)
    change = subject.NoteChange(
        status="M", path="scratchboard.md", kind="text",
        content="# Python\nFixed routing\n\n# Career\nPrepared review\n",
    )
    fallback = subject._fallback_distillation(change)
    parsed = {
        "segments": [
            {
                "section": "Python", "start_line": 1, "end_line": 2,
                "moment": "Fixed routing", "core_topic": "python",
            },
            {
                "section": "Career", "start_line": 4, "end_line": 99,
                "moment": "Prepared the review", "core_topic": "career",
            },
        ]
    }

    segments = subject._segments_from_parsed(
        parsed, fallback, max_segments=repository.max_topics_per_note,
        max_line=5,
    )

    assert [(item["section"], item["start_line"], item["end_line"]) for item in segments] == [
        ("Python", 1, 2), ("Career", 4, 5),
    ]
    assert [item["core_topic"] for item in segments] == ["python", "career"]


def test_segment_references_include_pinned_lines_and_actual_file(tmp_path):
    repository, _ = _repository(tmp_path)
    change = subject.NoteChange(status="M", path="Logs/today.md", kind="text")
    local = repository.host_path / "Logs" / "today.md"
    local.parent.mkdir()
    local.write_text("note\n", encoding="utf-8")

    references = subject._segment_references(
        repository, "abc123", change, {"start_line": 3, "end_line": 8},
    )

    assert references[0].endswith("/blob/abc123/Logs/today.md#L3-L8")
    assert references[1] == str(local.resolve())


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
    monkeypatch.setattr(subject, "distill_note_segments", lambda *a, **k: [{"skip": False}])
    monkeypatch.setattr(subject, "_write_entry", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("write failed")))
    monkeypatch.setattr(subject, "store_ingest_cursor", lambda *a: stored.append(a))
    monkeypatch.setattr(subject, "_head", lambda repo: "new-head")

    result = subject.ingest_notes_activity(repository_names=["notes"], synthesize=False)

    assert result["repositories"]["notes"]["cursor_advanced"] is False
    assert stored == []


def test_topic_entries_and_summary_share_the_daily_cap(monkeypatch, tmp_path):
    repository, baseline = _repository(tmp_path)
    repository = replace(repository, max_entries=3, max_topics_per_note=4)
    changes = [
        subject.NoteChange(status="M", path="one.md", kind="text", content="one"),
        subject.NoteChange(status="M", path="two.md", kind="text", content="two"),
    ]
    topic = {
        "skip": False, "moment": "topic", "what_happened": "detail",
        "core_topic": "topic", "section": "Heading", "start_line": 1,
        "end_line": 1,
    }
    writes = []
    stored = []
    monkeypatch.setattr(subject, "get_note_repositories", lambda: {"notes": repository})
    monkeypatch.setattr(subject, "recent_pull_succeeded", lambda *a, **k: True)
    monkeypatch.setattr(subject, "load_ingest_cursor", lambda name: baseline)
    monkeypatch.setattr(subject, "_head", lambda repo: "new-head")
    monkeypatch.setattr(subject, "collect_note_changes", lambda *a, **k: {"changes": changes})
    monkeypatch.setattr(subject, "distill_note_segments", lambda *a, **k: [dict(topic) for _ in range(3)])
    monkeypatch.setattr(subject, "distill_change_summary", lambda *a, **k: dict(topic, section="Overflow"))
    monkeypatch.setattr(
        subject, "_write_entry",
        lambda repo, distilled, **kwargs: writes.append((distilled, kwargs)) or (True, True),
    )
    monkeypatch.setattr(subject, "store_ingest_cursor", lambda *args: stored.append(args))

    result = subject.ingest_notes_activity(repository_names=["notes"], synthesize=True)
    detail = result["repositories"]["notes"]

    assert result["entries_written"] == 3
    assert detail["topic_entries"] == 2
    assert detail["summarized"] == 2
    assert len(writes) == repository.max_entries
    assert writes[-1][0]["section"] == "Overflow"
    assert stored == [("notes", "new-head")]
