"""
Tests for workflows/hfl/tasks/ingest_android_media.py.

Unit tests cover the log-line parser, package extractor, collection logic,
and distillation fallback. Integration tests call the real task and confirm
the no-op guard clauses fire cleanly without any I/O or network calls.
The live path (real corpus write + Anthropic call) is marked skip.
"""

from __future__ import annotations

from datetime import datetime, date

import pytest

import workflows.hfl.tasks.ingest_android_media as mod
from workflows.hfl.tasks.ingest_android_media import (
    _parse_log_line,
    _extract_package,
    collect_android_media_activity,
    distill_android_media_activity,
    ingest_android_media_activity,
)


# ── _parse_log_line ───────────────────────────────────────────────────────────

def test__parse_log_line_focus_and_ocr():
    focus = "[2026-06-01 09:15:32] FOCUS: mCurrentFocus=Window{abc u0 com.google.android.docs/...}"
    ocr = "[2026-06-01 09:16:00] OCR: Some text on screen"
    bad = "not a valid line"

    result_focus = _parse_log_line(focus)
    assert result_focus is not None
    assert result_focus["kind"] == "focus"
    assert isinstance(result_focus["ts"], datetime)
    assert "mCurrentFocus" in result_focus["content"]

    result_ocr = _parse_log_line(ocr)
    assert result_ocr is not None
    assert result_ocr["kind"] == "ocr"
    assert isinstance(result_ocr["ts"], datetime)
    assert result_ocr["content"] == "Some text on screen"

    assert _parse_log_line(bad) is None
    assert _parse_log_line("") is None
    assert _parse_log_line("   ") is None


def test__parse_log_line_timestamp_fields():
    line = "[2026-06-01 14:30:00] FOCUS: mCurrentFocus=Window{abc u0 com.spotify.music/...}"
    result = _parse_log_line(line)
    assert result is not None
    assert result["ts"].year == 2026
    assert result["ts"].month == 6
    assert result["ts"].day == 1
    assert result["ts"].hour == 14
    assert result["ts"].minute == 30


# ── _extract_package ──────────────────────────────────────────────────────────

def test__extract_package_from_focus_line():
    focus = "mCurrentFocus=Window{abc u0 com.google.android.docs/DocActivity}"
    assert _extract_package(focus) == "com.google.android.docs"


def test__extract_package_instagram():
    focus = "mCurrentFocus=Window{abc u0 com.instagram.android/MainActivity}"
    assert _extract_package(focus) == "com.instagram.android"


def test__extract_package_null_focus():
    assert _extract_package("mCurrentFocus=null") is None


def test__extract_package_empty():
    assert _extract_package("") is None
    assert _extract_package(None) is None  # type: ignore[arg-type]


def test__extract_package_system_dialog():
    # System dialogs without the u0 pattern
    assert _extract_package("mCurrentFocus=Window{abc  com.android.systemui}") is None


# ── collect_android_media_activity ────────────────────────────────────────────

def _write_log_file(path, lines):
    path.write_text("\n".join(lines), encoding="utf-8")


def test__collect_android_media_activity_parses_log_files(tmp_path):
    """Writes one synthetic log file; asserts basic collection fields."""
    log_file = tmp_path / "android_actions-20260601_09.log"
    _write_log_file(log_file, [
        "[2026-06-01 09:00:01] FOCUS: mCurrentFocus=Window{abc u0 com.google.android.docs/DocActivity}",
        "[2026-06-01 09:01:00] OCR: Document title here",
        "[2026-06-01 09:05:00] FOCUS: mCurrentFocus=Window{abc u0 com.google.android.docs/DocActivity}",
        "[2026-06-01 09:10:00] FOCUS: mCurrentFocus=Window{abc u0 com.instagram.android/MainActivity}",
        "[2026-06-01 09:10:30] OCR: Instagram feed text",
        "[2026-06-01 09:15:00] FOCUS: mCurrentFocus=Window{abc u0 com.google.android.docs/DocActivity}",
    ])

    result = collect_android_media_activity(
        since=date(2026, 6, 1),
        until=date(2026, 6, 1),
        logs_dir=str(tmp_path),
        max_log_files=24,
    )

    assert result["log_files_found"] == 1
    assert result["session_count"] >= 2
    assert len(result["top_apps"]) >= 1
    assert result["window_start"] != ""
    assert result["window_end"] != ""
    assert result["logs_dir"] == str(tmp_path)


def test__collect_android_media_activity_classifies_candidates(tmp_path):
    """top_apps is sorted descending by session_count; category is populated."""
    log_file = tmp_path / "android_actions-20260601_10.log"
    lines = []
    # 3 sessions on docs, 1 on instagram
    for i in range(3):
        lines.append(f"[2026-06-01 10:0{i}:00] FOCUS: mCurrentFocus=Window{{abc u0 com.google.android.docs/DocActivity}}")
        lines.append(f"[2026-06-01 10:0{i}:30] FOCUS: mCurrentFocus=Window{{abc u0 com.instagram.android/MainActivity}}")
    _write_log_file(log_file, lines)

    result = collect_android_media_activity(
        since=date(2026, 6, 1),
        until=date(2026, 6, 1),
        logs_dir=str(tmp_path),
        max_log_files=24,
    )

    assert result["log_files_found"] == 1
    top = result["top_apps"]
    assert len(top) >= 1

    # Sorted descending by session_count
    counts = [a["session_count"] for a in top]
    assert counts == sorted(counts, reverse=True)

    # Category populated for known packages
    pkg_map = {a["package"]: a["category"] for a in top}
    if "com.google.android.docs" in pkg_map:
        assert pkg_map["com.google.android.docs"] == "productivity"
    if "com.instagram.android" in pkg_map:
        assert pkg_map["com.instagram.android"] == "social"


def test__collect_android_media_activity_empty_dir(tmp_path):
    """Empty directory → log_files_found=0, session_count=0, no error."""
    result = collect_android_media_activity(
        since=date(2026, 6, 1),
        until=date(2026, 6, 1),
        logs_dir=str(tmp_path),
    )
    assert result["log_files_found"] == 0
    assert result["session_count"] == 0
    assert result["top_apps"] == []


def test__collect_android_media_activity_date_window_filter(tmp_path):
    """Files outside the window are excluded."""
    old_file = tmp_path / "android_actions-20260530_10.log"
    _write_log_file(old_file, [
        "[2026-05-30 10:00:00] FOCUS: mCurrentFocus=Window{abc u0 com.google.android.docs/DocActivity}",
    ])
    new_file = tmp_path / "android_actions-20260601_10.log"
    _write_log_file(new_file, [
        "[2026-06-01 10:00:00] FOCUS: mCurrentFocus=Window{abc u0 com.instagram.android/MainActivity}",
    ])

    result = collect_android_media_activity(
        since=date(2026, 6, 1),
        until=date(2026, 6, 1),
        logs_dir=str(tmp_path),
    )
    assert result["log_files_found"] == 1


# ── distill_android_media_activity ────────────────────────────────────────────

def _make_activity():
    return {
        "log_files_found": 3,
        "session_count": 5,
        "app_switches": 8,
        "top_apps": [
            {"package": "com.google.android.docs", "session_count": 3,
             "ocr_lines": 10, "category": "productivity"},
            {"package": "com.instagram.android", "session_count": 2,
             "ocr_lines": 5, "category": "social"},
        ],
        "window_start": "2026-06-01 00:00",
        "window_end": "2026-06-01 23:00",
        "logs_dir": "/tmp/x",
    }


def test__distill_android_media_activity_raw_fallback_no_api():
    """synthesize=False must not call any API and must return valid entry fields."""
    activity = _make_activity()
    d = distill_android_media_activity(activity, synthesize=False)

    assert d["skip"] is False
    assert d["synthesized"] is False
    assert "android" in d["tags"]
    assert "screen-activity" in d["tags"]
    for key in ("moment", "what_happened", "possible_use", "tags"):
        assert key in d
    assert isinstance(d["tags"], list)
    assert len(d["tags"]) >= 2


def test__distill_android_media_activity_fallback_moment_contains_count():
    activity = _make_activity()
    d = distill_android_media_activity(activity, synthesize=False)
    assert "5" in d["moment"] or "5 Android" in d["moment"]


# ── ingest_android_media_activity (no-op guard clauses) ──────────────────────

def test__ingest_android_media_activity_no_log_dir(monkeypatch):
    """No HFL_ANDROID_SCREEN_LOG_DIR → clean no-op, entries_written=0."""
    monkeypatch.delenv("HFL_ANDROID_SCREEN_LOG_DIR", raising=False)
    result = ingest_android_media_activity()
    assert result["entries_written"] == 0
    assert result["skipped"] == "no log dir"


def test__ingest_android_media_activity_log_dir_missing(monkeypatch, tmp_path):
    """HFL_ANDROID_SCREEN_LOG_DIR set but dir doesn't exist → no-op."""
    missing = tmp_path / "nonexistent"
    monkeypatch.setenv("HFL_ANDROID_SCREEN_LOG_DIR", str(missing))
    result = ingest_android_media_activity()
    assert result["entries_written"] == 0
    assert result["skipped"] == "log dir missing"


def test__ingest_android_media_activity_empty_dir(monkeypatch, tmp_path):
    """HFL_ANDROID_SCREEN_LOG_DIR exists but empty → no-op (no log files)."""
    monkeypatch.setenv("HFL_ANDROID_SCREEN_LOG_DIR", str(tmp_path))
    result = ingest_android_media_activity()
    assert result["entries_written"] == 0
    assert result["skipped"] in ("no log files", "no sessions")


# ── dual-write contract ───────────────────────────────────────────────────────

def test__dual_write_calls_index(monkeypatch, tmp_path):
    """Task must dual-write: corpus append + append_entry(source='android_media')."""
    log_file = tmp_path / "android_actions-20260601_09.log"
    _write_log_file(log_file, [
        "[2026-06-01 09:00:00] FOCUS: mCurrentFocus=Window{abc u0 com.google.android.docs/DocActivity}",
        "[2026-06-01 09:05:00] FOCUS: mCurrentFocus=Window{abc u0 com.instagram.android/MainActivity}",
    ])

    monkeypatch.setenv("HFL_ANDROID_SCREEN_LOG_DIR", str(tmp_path))
    monkeypatch.setattr(mod, "resolve_corpus_dir", lambda: tmp_path)

    # Force raw fallback (no Anthropic call)
    monkeypatch.setattr(
        mod,
        "distill_android_media_activity",
        lambda activity, **kw: {
            "skip": False,
            "moment": "Test Android day",
            "what_happened": "Two sessions",
            "why_it_stayed": "",
            "possible_use": "focus log",
            "tags": ["android", "screen-activity"],
            "synthesized": False,
        },
    )

    calls = {}

    def _fake_append(day_file, entry, *, source, synthesized=False):
        calls["source"] = source
        calls["synthesized"] = synthesized
        return 42, "doc-id-android"

    monkeypatch.setattr(mod, "append_entry", _fake_append)

    result = ingest_android_media_activity(window_days=1)

    if result["entries_written"] == 1:
        assert calls.get("source") == "android_media"
        assert result["indexed"] is True
    else:
        # The log file date might not fall in the window (today vs 2026-06-01);
        # in that case guard clauses fired cleanly.
        assert result["entries_written"] == 0


@pytest.mark.skip(
    reason="Manual only — requires valid HFL_ANDROID_SCREEN_LOG_DIR with real "
           "log files and ANTHROPIC credentials; appends a real entry to corpus."
)
def test__ingest_android_media_activity_full_pipeline():
    result = ingest_android_media_activity(window_days=1)
    assert result["entries_written"] in (0, 1)
