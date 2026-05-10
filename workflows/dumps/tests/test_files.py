"""Unit tests for workflows/dumps/files.py — pure logic, no SSH, no Trello."""
from datetime import datetime, timedelta
from pathlib import Path

import pytest

from workflows.dumps.files import (
    CollectedFile,
    format_dump_dir_name,
    group_by_source,
    iter_recent_files,
    previous_day_window,
)


# ── Workflow (none — this module is pure helpers) ─────────────────────────────

# ── Unit / function ───────────────────────────────────────────────────────────

def test__previous_day_window_at_midday():
    now = datetime(2026, 5, 10, 12, 0, 0)
    start, end = previous_day_window(now)
    assert start == datetime(2026, 5, 9)
    assert end == datetime(2026, 5, 10)


def test__previous_day_window_just_after_midnight():
    """Beat fires at 00:00:30 on day N → previous-day window is day N-1."""
    now = datetime(2026, 5, 10, 0, 0, 30)
    start, end = previous_day_window(now)
    assert start == datetime(2026, 5, 9)
    assert end == datetime(2026, 5, 10)


def test__format_dump_dir_name():
    assert format_dump_dir_name(
        "windows-work-all", datetime(2026, 5, 9)
    ) == "windows-work-all-daily-dumps-2026-05-09"


def test__iter_recent_files_filters_by_mtime(tmp_path: Path):
    """Files older than the window are skipped; recent ones are yielded."""
    src = tmp_path / "src"
    src.mkdir()
    old = src / "old.txt"
    new = src / "new.txt"
    old.write_text("o")
    new.write_text("n")
    # Anchor times ON the previous-day window so the test is deterministic
    # regardless of when (in the day) it runs.
    start, end = previous_day_window()
    in_window = start + timedelta(hours=12)              # noon yesterday
    long_ago = start - timedelta(days=29)                # safely before window
    import os
    os.utime(old, (long_ago.timestamp(), long_ago.timestamp()))
    os.utime(new, (in_window.timestamp(), in_window.timestamp()))

    matched = list(iter_recent_files([src], start, end))
    names = [f.path.name for f in matched]
    assert "new.txt" in names
    assert "old.txt" not in names


def test__iter_recent_files_preserves_relative_path(tmp_path: Path):
    src = tmp_path / "src"
    nested = src / "sub" / "deep"
    nested.mkdir(parents=True)
    f = nested / "file.txt"
    f.write_text("x")
    start, end = previous_day_window()
    in_window = start + timedelta(hours=12)
    import os
    os.utime(f, (in_window.timestamp(), in_window.timestamp()))

    matched = list(iter_recent_files([src], start, end))
    assert len(matched) == 1
    assert matched[0].relative == Path("sub") / "deep" / "file.txt"
    assert matched[0].source_root == src


def test__iter_recent_files_skips_missing_root(tmp_path: Path):
    """Non-existent source root is silently skipped (not an error)."""
    matched = list(iter_recent_files(
        [tmp_path / "does-not-exist"],
        datetime.now() - timedelta(days=1),
        datetime.now(),
    ))
    assert matched == []


def test__group_by_source_buckets_correctly(tmp_path: Path):
    a = tmp_path / "a"; a.mkdir()
    b = tmp_path / "b"; b.mkdir()
    files = [
        CollectedFile(source_root=a, path=a / "1", relative=Path("1"), mtime=datetime.now()),
        CollectedFile(source_root=a, path=a / "2", relative=Path("2"), mtime=datetime.now()),
        CollectedFile(source_root=b, path=b / "3", relative=Path("3"), mtime=datetime.now()),
    ]
    grouped = group_by_source(files)
    assert set(grouped.keys()) == {a, b}
    assert len(grouped[a]) == 2
    assert len(grouped[b]) == 1
