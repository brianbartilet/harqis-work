from __future__ import annotations

from datetime import datetime
from pathlib import Path

from scripts.agents.hfl.archive_corpus import archive_corpus, document_date


def _write(path: Path, text: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def test_document_date_prefers_created_metadata_over_title_and_filename(tmp_path):
    source = _write(
        tmp_path / "2025-01-01.md",
        "---\ncreated: 2024-03-14T09:30:00+08:00\ntitle: Notes from 2023-02-01\n---\n# 2022-01-01\n",
    )

    assert document_date(source) == datetime(2024, 3, 14).date()


def test_document_date_uses_hfl_header_or_weekly_rollup_name_without_mtime(tmp_path):
    hfl = _write(tmp_path / "daily.md", "## 2025-11-09 18:40\nMoment: Test\n")
    rollup = _write(
        tmp_path / "2026-W22-rollup.md",
        "# Weekly rollup — 2026-W22\nWindow: last 7 days · 2026-05-24 → 2026-05-30\n",
    )

    assert document_date(hfl) == datetime(2025, 11, 9).date()
    assert document_date(rollup) == datetime(2026, 5, 25).date()


def test_archive_moves_only_prior_month_root_markdown_and_is_idempotent(tmp_path):
    old = _write(tmp_path / "old.md", "# Notes from 2026-06-15\n")
    current = _write(tmp_path / "current.md", "## 2026-07-02 10:00\nMoment: Current\n")
    hidden = _write(tmp_path / ".hidden.md", "## 2026-06-01\n")
    nested = _write(tmp_path / "time-capsule" / "capsule.md", "# 2026-05-01\n")
    undated = _write(tmp_path / "undated.md", "# Notes without a date\n")

    result = archive_corpus(tmp_path, today=datetime(2026, 7, 21).date())

    assert result.moved == 1
    assert result.current_month == 1
    assert result.undated == ("undated.md",)
    assert not old.exists()
    assert (tmp_path / "2026" / "Jun" / "old.md").is_file()
    assert current.is_file()
    assert hidden.is_file()
    assert nested.is_file()

    repeated = archive_corpus(tmp_path, today=datetime(2026, 7, 21).date())
    assert repeated.moved == 0


def test_archive_does_not_overwrite_conflicting_destination(tmp_path):
    source = _write(tmp_path / "same.md", "## 2026-06-10\nMoment: Source\n")
    destination = _write(tmp_path / "2026" / "Jun" / "same.md", "different\n")

    result = archive_corpus(tmp_path, today=datetime(2026, 7, 1).date())

    assert source.is_file()
    assert destination.read_text(encoding="utf-8") == "different\n"
    assert result.conflicts == ("same.md",)
