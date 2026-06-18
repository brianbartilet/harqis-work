"""
Tests for workflows/hfl/tasks/ingest_android_session.py.

Unit tests cover the pure aggregation functions (no I/O, no LLM).
Integration tests call the real task exactly as Beat will; the default
(no data path configured) is a guaranteed no-op — no network, no file writes.
"""

from __future__ import annotations

import json
from datetime import date, datetime, timedelta
from pathlib import Path

import pytest

import workflows.hfl.tasks.ingest_android_session as mod
from workflows.hfl.tasks.ingest_android_session import (
    _categorize_app,
    _classify_focus_windows,
    _classify_fragmented_periods,
    _category_breakdown,
    _derive_idle_blocks,
    _derive_screen_sessions,
    aggregate_sessions,
    collect_android_session_activity,
    distill_android_session_activity,
    ingest_android_session_activity,
    parse_session_jsonl,
)


# ── helpers ───────────────────────────────────────────────────────────────────

def _ts(offset_sec: int = 0) -> int:
    """Return a unix timestamp for today at midnight + offset_sec."""
    today = datetime.now().date()
    return int(datetime(today.year, today.month, today.day).timestamp()) + offset_sec


def _jsonl(*events: dict) -> str:
    return "\n".join(json.dumps(e) for e in events)


def _today() -> date:
    return datetime.now().date()


# ── parse_session_jsonl ───────────────────────────────────────────────────────

def test__parse_session_jsonl_valid_events():
    raw = _jsonl(
        {"ts": _ts(10), "type": "screen_on"},
        {"ts": _ts(300), "type": "app_foreground", "app": "com.android.chrome"},
        {"ts": _ts(600), "type": "app_background", "app": "com.android.chrome"},
        {"ts": _ts(700), "type": "unlock"},
        {"ts": _ts(800), "type": "screen_off"},
        {"ts": _ts(900), "type": "charging_on"},
        {"ts": _ts(1200), "type": "charging_off"},
    )
    events = parse_session_jsonl(raw)
    assert len(events) == 7
    types = [e["type"] for e in events]
    assert "screen_on" in types
    assert "unlock" in types
    assert "app_foreground" in types
    fg = next(e for e in events if e["type"] == "app_foreground")
    assert fg["app"] == "com.android.chrome"
    # Sorted by ts ascending
    timestamps = [e["ts"] for e in events]
    assert timestamps == sorted(timestamps)


def test__parse_session_jsonl_skips_malformed():
    raw = "\n".join([
        "not json at all",
        '{"ts": "bad_ts", "type": "screen_on"}',
        '{"type": "screen_on"}',                 # missing ts
        '{"ts": 100, "type": "unknown_event"}',  # unknown type
        '{"ts": ' + str(_ts(1)) + ', "type": "screen_on"}',  # valid
        "",
        "   ",
    ])
    events = parse_session_jsonl(raw)
    assert len(events) == 1
    assert events[0]["type"] == "screen_on"


def test__parse_session_jsonl_empty_string():
    assert parse_session_jsonl("") == []
    assert parse_session_jsonl("   \n  \n") == []


def test__parse_session_jsonl_sorts_by_ts():
    raw = _jsonl(
        {"ts": _ts(300), "type": "screen_off"},
        {"ts": _ts(100), "type": "screen_on"},
        {"ts": _ts(200), "type": "unlock"},
    )
    events = parse_session_jsonl(raw)
    assert [e["ts"] for e in events] == sorted(e["ts"] for e in events)


# ── _categorize_app ───────────────────────────────────────────────────────────

def test__categorize_app_exact_match():
    assert _categorize_app("com.android.chrome") == "web"
    assert _categorize_app("com.spotify.music") == "music"
    assert _categorize_app("com.whatsapp") == "messaging"
    assert _categorize_app("com.linkedin.android") == "professional"
    assert _categorize_app("com.google.android.gm") == "email"


def test__categorize_app_prefix_match():
    # com.android.settings has an exact-match entry -> "settings" (exact wins over prefix)
    assert _categorize_app("com.android.settings") == "settings"
    # generic com.android.* package without exact entry -> "system" (prefix fallback)
    assert _categorize_app("com.android.somethingelse") == "system"
    assert _categorize_app("com.microsoft.outlook") == "productivity"
    assert _categorize_app("com.google.android.calendar") == "calendar"


def test__categorize_app_unknown():
    assert _categorize_app("com.example.somerandommapp") == "other"
    assert _categorize_app("") == "other"


# ── _derive_screen_sessions ───────────────────────────────────────────────────

def test__derive_screen_sessions_pairs_on_off():
    events = [
        {"ts": _ts(100), "type": "screen_on"},
        {"ts": _ts(460), "type": "screen_off"},
    ]
    sessions = _derive_screen_sessions(events)
    assert len(sessions) == 1
    assert sessions[0]["duration_min"] == pytest.approx(6.0)
    assert sessions[0]["start_ts"] == _ts(100)
    assert sessions[0]["end_ts"] == _ts(460)


def test__derive_screen_sessions_multiple_pairs():
    events = [
        {"ts": _ts(0), "type": "screen_on"},
        {"ts": _ts(300), "type": "screen_off"},
        {"ts": _ts(600), "type": "screen_on"},
        {"ts": _ts(1200), "type": "screen_off"},
    ]
    sessions = _derive_screen_sessions(events)
    assert len(sessions) == 2
    assert sessions[0]["duration_min"] == pytest.approx(5.0)
    assert sessions[1]["duration_min"] == pytest.approx(10.0)


def test__derive_screen_sessions_unclosed_kept():
    events = [
        {"ts": _ts(0), "type": "screen_on"},
        {"ts": _ts(500), "type": "unlock"},  # no screen_off
    ]
    sessions = _derive_screen_sessions(events)
    assert len(sessions) == 1
    assert sessions[0]["end_ts"] == _ts(500)


# ── _derive_idle_blocks ───────────────────────────────────────────────────────

def test__derive_idle_blocks_detects_gap():
    today = _today()
    day_start = int(datetime(today.year, today.month, today.day).timestamp())
    day_end = day_start + 86400
    sessions = [
        {"start_ts": day_start + 3600, "end_ts": day_start + 5400, "duration_min": 30},
        {"start_ts": day_start + 7500, "end_ts": day_start + 9000, "duration_min": 25},
    ]
    # gap between sessions is 7500 - 5400 = 2100 sec = 35 min
    idle = _derive_idle_blocks(sessions, day_start, day_end, min_idle_min=30)
    gap_durations = [b["duration_min"] for b in idle]
    assert any(d >= 34 for d in gap_durations), f"Expected a ~35-min idle, got {gap_durations}"


def test__derive_idle_blocks_no_sessions_full_day():
    today = _today()
    day_start = int(datetime(today.year, today.month, today.day).timestamp())
    day_end = day_start + 86400
    idle = _derive_idle_blocks([], day_start, day_end, min_idle_min=30)
    assert len(idle) == 1
    assert idle[0]["duration_min"] >= 1439


# ── _classify_focus_windows ───────────────────────────────────────────────────

def test__classify_focus_windows_detects_dominant_category():
    # 30-min screen session; productivity = 25 min (1500 sec), web = 5 min (300 sec)
    base = _ts(3600)
    screen_sessions = [{"start_ts": base, "end_ts": base + 1800, "duration_min": 30.0}]
    app_sessions = [
        {"app": "com.google.android.apps.docs", "category": "productivity",
         "start_ts": base, "end_ts": base + 1500, "duration_sec": 1500},
        {"app": "com.android.chrome", "category": "web",
         "start_ts": base + 1500, "end_ts": base + 1800, "duration_sec": 300},
    ]
    focus = _classify_focus_windows(
        screen_sessions, app_sessions,
        focus_min_duration_min=20,
        focus_dominance_pct=0.55,
    )
    assert len(focus) == 1
    assert focus[0]["category"] == "productivity"
    assert focus[0]["dominance_pct"] >= 80


def test__classify_focus_windows_short_session_excluded():
    base = _ts(3600)
    screen_sessions = [{"start_ts": base, "end_ts": base + 900, "duration_min": 15.0}]
    app_sessions = [
        {"app": "com.android.chrome", "category": "web",
         "start_ts": base, "end_ts": base + 900, "duration_sec": 900},
    ]
    focus = _classify_focus_windows(screen_sessions, app_sessions, focus_min_duration_min=20)
    assert focus == []


# ── _classify_fragmented_periods ──────────────────────────────────────────────

def test__classify_fragmented_periods_detects_burst():
    base = _ts(3600)
    # 5 sessions of 2 min each, spaced 3 min apart — all within 20 min
    screen_sessions = [
        {"start_ts": base + i * 300, "end_ts": base + i * 300 + 120, "duration_min": 2.0}
        for i in range(5)
    ]
    periods = _classify_fragmented_periods(
        screen_sessions,
        fragment_max_duration_min=5.0,
        fragment_window_min=30,
        fragment_min_count=4,
    )
    assert len(periods) == 1
    assert periods[0]["session_count"] == 5


def test__classify_fragmented_periods_below_threshold_excluded():
    base = _ts(3600)
    # Only 3 short sessions — below min_count=4
    screen_sessions = [
        {"start_ts": base + i * 300, "end_ts": base + i * 300 + 120, "duration_min": 2.0}
        for i in range(3)
    ]
    periods = _classify_fragmented_periods(screen_sessions, fragment_min_count=4)
    assert periods == []


# ── aggregate_sessions ────────────────────────────────────────────────────────

def test__aggregate_sessions_counts_unlocks():
    today = _today()
    base = _ts(3600)
    events = [
        {"ts": base + 0, "type": "screen_on"},
        {"ts": base + 60, "type": "unlock"},
        {"ts": base + 120, "type": "unlock"},
        {"ts": base + 180, "type": "unlock"},
        {"ts": base + 3600, "type": "screen_off"},
    ]
    result = aggregate_sessions(events, today, today)
    assert result["unlock_count"] == 3


def test__aggregate_sessions_empty_events_returns_zeros():
    today = _today()
    result = aggregate_sessions([], today, today)
    assert result["unlock_count"] == 0
    assert result["screen_session_count"] == 0
    assert result["total_screen_time_min"] == 0
    assert result["focus_window_count"] == 0
    assert result["fragmented_period_count"] == 0
    assert result["focus_windows"] == []
    assert result["fragmented_periods"] == []
    assert result["category_breakdown"] == {}


def test__aggregate_sessions_filters_to_window():
    today = _today()
    yesterday = today - timedelta(days=1)
    base_today = _ts(3600)
    base_yesterday = int(datetime(yesterday.year, yesterday.month, yesterday.day).timestamp()) + 3600
    events = [
        {"ts": base_yesterday, "type": "screen_on"},
        {"ts": base_yesterday + 600, "type": "screen_off"},
        {"ts": base_today, "type": "screen_on"},
        {"ts": base_today + 600, "type": "screen_off"},
    ]
    result = aggregate_sessions(events, today, today)
    assert result["screen_session_count"] == 1


# ── distill_android_session_activity ─────────────────────────────────────────

def test__distill_raw_fallback_no_api():
    """synthesize=False must not call any API and must return entry fields."""
    activity = {
        "date": "2026-06-01",
        "unlock_count": 42,
        "total_screen_time_min": 150.0,
        "screen_session_count": 18,
        "focus_window_count": 2,
        "fragmented_period_count": 1,
        "idle_block_count": 1,
        "longest_idle_min": 75.0,
        "charging_count": 1,
        "category_breakdown": {"productivity": 5400, "web": 2700},
        "focus_windows": [],
        "fragmented_periods": [],
        "idle_blocks": [],
        "charging_periods": [],
        "screen_sessions": [],
        "_events": [],
    }
    d = distill_android_session_activity(activity, synthesize=False)
    assert d["skip"] is False
    assert d["synthesized"] is False
    for key in ("moment", "what_happened", "possible_use", "tags"):
        assert key in d
    assert "android" in d["moment"].lower() or "unlock" in d["moment"].lower()


def test__distill_raw_fallback_includes_unlock_count():
    activity = {
        "date": "2026-06-01",
        "unlock_count": 7,
        "total_screen_time_min": 30.0,
        "screen_session_count": 5,
        "focus_window_count": 0,
        "fragmented_period_count": 0,
        "idle_block_count": 0,
        "longest_idle_min": 0,
        "charging_count": 0,
        "category_breakdown": {},
        "focus_windows": [],
        "fragmented_periods": [],
        "idle_blocks": [],
        "charging_periods": [],
        "screen_sessions": [],
        "_events": [],
    }
    d = distill_android_session_activity(activity, synthesize=False)
    assert "7 unlock" in d["moment"]


# ── ingest_android_session_activity (integration) ─────────────────────────────

def test__ingest_activity_no_data_path(monkeypatch):
    """No data path configured -> clean no-op, no file I/O."""
    monkeypatch.setattr(mod, "_resolve_data_path", lambda: None)
    result = ingest_android_session_activity()
    assert result["entries_written"] == 0
    assert result["skipped"] == "no data path"


def test__ingest_activity_file_not_found(monkeypatch, tmp_path):
    """Data path points to a nonexistent file -> clean no-op."""
    missing = tmp_path / "does_not_exist.jsonl"
    monkeypatch.setattr(mod, "_resolve_data_path", lambda: missing)
    result = ingest_android_session_activity()
    assert result["entries_written"] == 0
    assert result["skipped"] == "file not found"


def test__ingest_activity_no_events(monkeypatch, tmp_path):
    """File exists but has no events in today's window -> clean no-op."""
    data_file = tmp_path / "session.jsonl"
    # Write events from far in the past — outside today's window
    data_file.write_text(
        json.dumps({"ts": 1000000, "type": "screen_on"}) + "\n" +
        json.dumps({"ts": 1000060, "type": "screen_off"}) + "\n"
    )
    monkeypatch.setattr(mod, "_resolve_data_path", lambda: data_file)
    result = ingest_android_session_activity()
    assert result["entries_written"] == 0
    assert result["skipped"] == "no events"


def test__dual_write_calls_index(monkeypatch, tmp_path):
    """Full pipeline: events today -> entry appended with source='android-session'."""
    base = _ts(3600)
    data_file = tmp_path / "session.jsonl"
    data_file.write_text("\n".join([
        json.dumps({"ts": base, "type": "screen_on"}),
        json.dumps({"ts": base + 60, "type": "unlock"}),
        json.dumps({"ts": base + 300, "type": "screen_off"}),
    ]))

    monkeypatch.setattr(mod, "_resolve_data_path", lambda: data_file)
    monkeypatch.setattr(mod, "resolve_corpus_dir", lambda: tmp_path)
    monkeypatch.setattr(
        mod, "distill_android_session_activity",
        lambda activity, **kw: {
            "skip": False,
            "moment": "Test session rhythm",
            "what_happened": "One session.",
            "why_it_stayed": "",
            "possible_use": "attention log",
            "tags": ["android", "session-rhythm"],
            "synthesized": False,
        },
    )

    calls: dict = {}

    def _fake_append(day_file, entry, *, source, synthesized=False):
        calls["source"] = source
        calls["synthesized"] = synthesized
        return 42, "doc-id-test"

    monkeypatch.setattr(mod, "append_entry", _fake_append)

    result = ingest_android_session_activity()
    assert result["entries_written"] == 1
    assert calls.get("source") == "android-session"
    assert result["indexed"] is True
