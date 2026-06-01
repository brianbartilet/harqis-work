"""
Tests for workflows/hfl/tasks/ingest_notifications.py.

Integration tests call the real task exactly as Beat will. The default
(no JSONL drop file in the configured inbox) is a guaranteed no-op — no IO
beyond a directory existence check, no side-effects. The live round-trip
(real JSONL file + optional Anthropic call + corpus write) is marked skip.
"""

from datetime import date, datetime
from pathlib import Path

import pytest

import workflows.hfl.tasks.ingest_notifications as mod
from workflows.hfl.tasks.ingest_notifications import (
    ingest_notification_activity,
    collect_notification_activity,
    distill_notification_activity,
    _parse_record,
    _fmt_top_apps,
    _fmt_categories,
    _fmt_peak_hours,
    _activity_body,
)


# ── Workflow (integration) ─────────────────────────────────────────────────────

def test__ingest_notification_activity_no_drop_file(tmp_path, monkeypatch):
    """Empty inbox → clean no-op, no corpus write, no LLM call."""
    monkeypatch.setattr(mod, "resolve_notifications_dir", lambda: tmp_path)
    result = ingest_notification_activity()
    assert result["entries_written"] == 0
    assert result["skipped"] == "no records"


@pytest.mark.skip(reason="Manual only — requires a real JSONL drop file and "
                         "optionally Anthropic creds; appends a real entry to "
                         "today's corpus.")
def test__ingest_notification_activity_full_pipeline():
    result = ingest_notification_activity(window_days=1)
    assert result["entries_written"] in (0, 1)


# ── _parse_record ─────────────────────────────────────────────────────────────

def test__parse_record_valid_minimal():
    line = '{"ts": "2026-06-01T09:15:22", "app": "com.whatsapp", "app_label": "WhatsApp", "category": "msg"}'
    r = _parse_record(line)
    assert r is not None
    assert r["app"] == "com.whatsapp"
    assert r["app_label"] == "WhatsApp"
    assert r["category"] == "msg"
    assert isinstance(r["ts"], datetime)


def test__parse_record_strips_private_fields():
    line = (
        '{"ts": "2026-06-01T09:15:22", "app": "com.whatsapp", "app_label": "WhatsApp",'
        ' "title": "Alice: hey!", "body": "Private message", "text": "More private"}'
    )
    r = _parse_record(line)
    assert r is not None
    assert "title" not in r
    assert "body" not in r
    assert "text" not in r
    assert r["app"] == "com.whatsapp"


def test__parse_record_unknown_category_normalises_to_other():
    line = '{"ts": "2026-06-01T09:15:22", "app": "com.example", "app_label": "Ex", "category": "unknown"}'
    r = _parse_record(line)
    assert r is not None
    assert r["category"] == "other"


def test__parse_record_all_valid_categories():
    for cat in ("msg", "call", "alarm", "sys", "media", "other"):
        line = f'{{"ts": "2026-06-01T09:00:00", "app": "com.x", "app_label": "X", "category": "{cat}"}}'
        r = _parse_record(line)
        assert r is not None, f"category '{cat}' should be valid"
        assert r["category"] == cat


def test__parse_record_missing_required_fields():
    assert _parse_record('{"app": "com.example", "app_label": "Ex"}') is None  # no ts
    assert _parse_record('{"ts": "2026-06-01T09:00:00", "app_label": "Ex"}') is None  # no app
    assert _parse_record("not json") is None
    assert _parse_record("") is None
    assert _parse_record("   ") is None
    assert _parse_record("# comment line") is None


def test__parse_record_bad_timestamp():
    line = '{"ts": "not-a-date", "app": "com.example", "app_label": "Ex"}'
    assert _parse_record(line) is None


def test__parse_record_app_label_falls_back_to_app():
    line = '{"ts": "2026-06-01T09:00:00", "app": "com.example"}'
    r = _parse_record(line)
    assert r is not None
    assert r["app_label"] == "com.example"


# ── collect_notification_activity ─────────────────────────────────────────────

def test__collect_aggregates_correctly(tmp_path):
    today = date.today()
    drop = tmp_path / f"android_notifications_{today.strftime('%Y%m%d')}.jsonl"
    drop.write_text(
        "\n".join([
            f'{{"ts": "{today.isoformat()}T09:00:00", "app": "com.whatsapp", "app_label": "WhatsApp", "category": "msg"}}',
            f'{{"ts": "{today.isoformat()}T09:30:00", "app": "com.whatsapp", "app_label": "WhatsApp", "category": "msg"}}',
            f'{{"ts": "{today.isoformat()}T11:00:00", "app": "com.gmail.android", "app_label": "Gmail", "category": "msg"}}',
            f'{{"ts": "{today.isoformat()}T14:00:00", "app": "com.android.systemui", "app_label": "System UI", "category": "sys"}}',
        ]),
        encoding="utf-8",
    )
    activity = collect_notification_activity(
        since=today, until=today, notifications_dir=tmp_path,
    )
    assert activity["total_count"] == 4
    assert activity["distinct_apps"] == 3
    assert activity["apps"]["WhatsApp"] == 2
    assert activity["apps"]["Gmail"] == 1
    assert activity["categories"]["msg"] == 3
    assert activity["categories"]["sys"] == 1
    assert "9" in activity["by_hour"]
    assert activity["by_hour"]["9"] == 2


def test__collect_no_drop_file_is_noop(tmp_path):
    today = date.today()
    activity = collect_notification_activity(
        since=today, until=today, notifications_dir=tmp_path,
    )
    assert activity["total_count"] == 0
    assert activity["distinct_apps"] == 0
    assert activity["apps"] == {}
    assert activity["categories"] == {}


def test__collect_skips_malformed_lines(tmp_path):
    today = date.today()
    drop = tmp_path / f"android_notifications_{today.strftime('%Y%m%d')}.jsonl"
    drop.write_text(
        "not json at all\n"
        f'{{"ts": "{today.isoformat()}T09:00:00", "app": "com.slack", "app_label": "Slack", "category": "msg"}}\n'
        '{"incomplete": \n',
        encoding="utf-8",
    )
    activity = collect_notification_activity(
        since=today, until=today, notifications_dir=tmp_path,
    )
    assert activity["total_count"] == 1
    assert activity["apps"]["Slack"] == 1


def test__collect_respects_max_records(tmp_path):
    today = date.today()
    drop = tmp_path / f"android_notifications_{today.strftime('%Y%m%d')}.jsonl"
    lines = [
        f'{{"ts": "{today.isoformat()}T09:0{i % 10}:00", "app": "com.app{i}", "app_label": "App{i}", "category": "sys"}}'
        for i in range(20)
    ]
    drop.write_text("\n".join(lines), encoding="utf-8")
    activity = collect_notification_activity(
        since=today, until=today, notifications_dir=tmp_path, max_records=5,
    )
    assert activity["total_count"] == 5


def test__collect_spans_multiple_days(tmp_path):
    today = date.today()
    yesterday = today - __import__("datetime").timedelta(days=1)
    for day in (today, yesterday):
        drop = tmp_path / f"android_notifications_{day.strftime('%Y%m%d')}.jsonl"
        drop.write_text(
            f'{{"ts": "{day.isoformat()}T10:00:00", "app": "com.x", "app_label": "X", "category": "msg"}}\n',
            encoding="utf-8",
        )
    activity = collect_notification_activity(
        since=yesterday, until=today, notifications_dir=tmp_path,
    )
    assert activity["total_count"] == 2


# ── formatting helpers ────────────────────────────────────────────────────────

def test__fmt_top_apps_sorts_descending_and_truncates():
    apps = {"WhatsApp": 34, "Gmail": 18, "Slack": 14, "YouTube": 5, "Maps": 2}
    result = _fmt_top_apps(apps, limit=3)
    assert "WhatsApp \xd734" in result
    assert "Gmail \xd718" in result
    assert "YouTube" not in result   # below the limit


def test__fmt_categories_respects_canonical_order():
    cats = {"sys": 5, "msg": 20, "call": 3}
    result = _fmt_categories(cats)
    assert result.index("msg") < result.index("sys")


def test__fmt_peak_hours_shows_top3():
    by_hour = {"9": 22, "14": 18, "10": 15, "20": 5}
    result = _fmt_peak_hours(by_hour)
    assert "9:00" in result
    assert "14:00" in result
    assert "20:00" not in result  # lowest, outside top 3


def test__fmt_peak_hours_empty():
    assert "no hourly data" in _fmt_peak_hours({})


def test__activity_body_contains_key_fields():
    activity = {
        "total_count": 87,
        "distinct_apps": 3,
        "apps": {"WhatsApp": 34, "Gmail": 18},
        "categories": {"msg": 48, "sys": 21},
        "by_hour": {"10": 22, "14": 18},
    }
    body = _activity_body(activity)
    assert "87" in body
    assert "WhatsApp" in body
    assert "msg" in body
    assert "10:00" in body


# ── distill_notification_activity ─────────────────────────────────────────────

def test__distill_raw_fallback_no_api():
    """synthesize=False must not call any API and must return valid entry fields."""
    activity = {
        "total_count": 40,
        "distinct_apps": 4,
        "apps": {"WhatsApp": 20, "Gmail": 10, "Slack": 7, "Calendar": 3},
        "categories": {"msg": 30, "sys": 10},
        "by_hour": {"9": 15, "14": 10, "18": 15},
    }
    d = distill_notification_activity(activity, synthesize=False)
    assert d["skip"] is False
    assert d["synthesized"] is False
    assert "40" in d["moment"]
    for key in ("moment", "what_happened", "possible_use", "tags"):
        assert key in d
    assert "android" in d["tags"]
    assert "notifications" in d["tags"]


# ── dual-write contract ───────────────────────────────────────────────────────

def test__dual_write_calls_index(monkeypatch, tmp_path):
    """Task must dual-write: corpus append + index_hfl_entry(source=android-notifications)."""
    today = date.today()
    drop = tmp_path / f"android_notifications_{today.strftime('%Y%m%d')}.jsonl"
    drop.write_text(
        f'{{"ts": "{today.isoformat()}T09:00:00", "app": "com.whatsapp", "app_label": "WhatsApp", "category": "msg"}}\n',
        encoding="utf-8",
    )

    monkeypatch.setattr(mod, "resolve_notifications_dir", lambda: tmp_path)
    monkeypatch.setattr(mod, "resolve_corpus_dir", lambda: tmp_path)
    monkeypatch.setattr(
        mod, "distill_notification_activity",
        lambda activity, **kw: {
            "skip": False,
            "moment": "A notification day",
            "what_happened": "40 notifications from 4 apps.",
            "why_it_stayed": "",
            "possible_use": "attention log",
            "tags": ["android", "notifications"],
            "synthesized": False,
        },
    )

    calls = {}

    def _fake_append(day_file, entry, *, source, synthesized=False):
        calls["source"] = source
        calls["synthesized"] = synthesized
        return 10, "doc-id-abc"

    monkeypatch.setattr(mod, "append_entry", _fake_append)

    result = ingest_notification_activity(window_days=1)
    assert result["entries_written"] == 1
    assert calls["source"] == "android-notifications"
    assert result["indexed"] is True


def test__task_returns_correct_shape_on_write(monkeypatch, tmp_path):
    """Return dict must include entries_written, total_count, distinct_apps, path, indexed."""
    today = date.today()
    drop = tmp_path / f"android_notifications_{today.strftime('%Y%m%d')}.jsonl"
    drop.write_text(
        f'{{"ts": "{today.isoformat()}T09:00:00", "app": "com.x", "app_label": "X", "category": "msg"}}\n'
        f'{{"ts": "{today.isoformat()}T10:00:00", "app": "com.y", "app_label": "Y", "category": "sys"}}\n',
        encoding="utf-8",
    )

    monkeypatch.setattr(mod, "resolve_notifications_dir", lambda: tmp_path)
    monkeypatch.setattr(mod, "resolve_corpus_dir", lambda: tmp_path)
    monkeypatch.setattr(
        mod, "distill_notification_activity",
        lambda activity, **kw: {
            "skip": False, "moment": "m", "what_happened": "w",
            "why_it_stayed": "", "possible_use": "attention log",
            "tags": ["android", "notifications"], "synthesized": False,
        },
    )
    monkeypatch.setattr(mod, "append_entry", lambda *a, **kw: (10, "doc-123"))

    result = ingest_notification_activity(window_days=1)
    assert result["entries_written"] == 1
    assert result["total_count"] == 2
    assert result["distinct_apps"] == 2
    assert "path" in result
    assert result["indexed"] is True
