"""
Tests for workflows/hfl/tasks/ingest_radar.py.

Integration tests call the real task exactly as Beat will. With no feed dir
configured (or none containing radar briefings) the task is a guaranteed
no-op — no network, no LLM, no corpus write. The live path (real feed read +
Anthropic synthesis + corpus write) is marked skip.
"""

from datetime import date, datetime

import pytest

import workflows.hfl.tasks.ingest_radar as radar
from workflows.hfl.tasks.ingest_radar import (
    ingest_radar_activity,
    collect_radar_activity,
    distill_radar_activity,
    _parse_feed_briefings,
    _strip_footer,
)


# A realistic two-block feed file as apps/desktop/helpers/feed.py writes it
# (newest prepended first; footer is a row of '>' from make_separator).
_FOOTER = ">" * 47
_FEED_TEXT = (
    f">> Start\n2026-06-23 16:00:00 :: show_daily_radar\n"
    f"TOP 3: ship radar ingest; reply to client; fix failed jobs\n"
    f"OVERDUE: PROJ-412 blocker\n\n{_FOOTER}\n\n"
    f">> Start\n2026-06-23 12:00:00 :: get_desktop_logs\n"
    f"unrelated desktop block — must be ignored\n\n{_FOOTER}\n\n"
    f">> Start\n2026-06-23 08:00:00 :: show_daily_radar\n"
    f"TOP 3: plan the day; invoice reply; standup\n\n{_FOOTER}\n\n"
)


# ── Workflow (integration) ────────────────────────────────────────────────────

def test__ingest_radar_activity_no_feed_dir(monkeypatch):
    """No feed dir on this host → clean no-op, no network, no corpus write."""
    monkeypatch.setattr(radar, "_resolve_feed_dir", lambda: None)
    result = ingest_radar_activity(cfg_id__anthropic="ANTHROPIC")
    assert result["entries_written"] == 0
    assert result["skipped"] == "no feed dir"


def test__ingest_radar_activity_no_briefings(monkeypatch, tmp_path):
    """Feed dir present but no radar blocks in window → no entry, no LLM."""
    monkeypatch.setattr(radar, "_resolve_feed_dir", lambda: tmp_path)
    result = ingest_radar_activity(cfg_id__anthropic="ANTHROPIC")
    assert result["entries_written"] == 0
    assert result["skipped"] == "no briefings"


def test__ingest_radar_activity_dual_write(monkeypatch, tmp_path):
    """Full happy path with a stubbed feed + distiller: builds ONE entry and
    calls index_hfl_entry (the dual-write contract). No network."""
    today = datetime.now().date()
    monkeypatch.setattr(radar, "_resolve_feed_dir", lambda: tmp_path)
    feed_file = tmp_path / f"hud-logs-{today.strftime('%Y%m%d')}.txt"
    feed_file.write_text(
        f">> Start\n{today.strftime('%Y-%m-%d')} 16:00:00 :: show_daily_radar\n"
        f"TOP 3: ship the radar ingest\n\n{_FOOTER}\n\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(radar, "resolve_corpus_dir", lambda: tmp_path)
    # Don't call Anthropic — force the raw fallback distiller.
    monkeypatch.setattr(
        radar, "distill_radar_activity",
        lambda activity, **kw: {
            "skip": False, "moment": "radar day", "what_happened": "did things",
            "why_it_stayed": "", "possible_use": "retro",
            "tags": ["radar"], "synthesized": False,
        },
    )
    indexed: dict = {}
    monkeypatch.setattr(
        radar, "append_entry",
        lambda day_file, entry, *, source, synthesized: (
            indexed.update(source=source, moment=entry.moment), (123, "doc-id"))[1],
    )
    result = ingest_radar_activity(window_days=2)
    assert result["entries_written"] == 1
    assert result["indexed"] is True
    assert indexed["source"] == "radar"


@pytest.mark.skip(reason="Manual only — live feed read + Anthropic synthesis; "
                         "appends a real entry to today's corpus.")
def test__ingest_radar_activity_full_pipeline():
    result = ingest_radar_activity(cfg_id__anthropic="ANTHROPIC", window_days=7)
    assert result["entries_written"] in (0, 1)


# ── Unit / function ───────────────────────────────────────────────────────────

def test__parse_feed_briefings_filters_func_and_window():
    msgs = _parse_feed_briefings(
        _FEED_TEXT, since=date(2026, 6, 22), until=date(2026, 6, 23)
    )
    # Two radar blocks; the desktop-logs block is dropped.
    assert len(msgs) == 2
    assert all("desktop block" not in m["text"] for m in msgs)
    assert any("PROJ-412" in m["text"] for m in msgs)
    assert msgs[0]["when"].startswith("2026-06-23")


def test__parse_feed_briefings_out_of_window():
    msgs = _parse_feed_briefings(
        _FEED_TEXT, since=date(2020, 1, 1), until=date(2020, 1, 2)
    )
    assert msgs == []


def test__strip_footer_removes_separator_and_padding():
    body = "line one\nline two\n\n" + ">" * 47 + "\n\n"
    out = _strip_footer(body)
    assert out == "line one\nline two"


def test__collect_radar_activity_reads_feed(tmp_path):
    f = tmp_path / "hud-logs-20260623.txt"
    f.write_text(_FEED_TEXT, encoding="utf-8")
    activity = collect_radar_activity(
        since=date(2026, 6, 23), until=date(2026, 6, 23), feed_dir=tmp_path
    )
    assert activity["briefing_count"] == 2
    assert str(f) in activity["feed_files"]
    # oldest-first ordering
    assert activity["briefings"][0]["when"] < activity["briefings"][1]["when"]


def test__collect_radar_activity_no_feed_dir_is_clean(monkeypatch):
    monkeypatch.setattr(radar, "_resolve_feed_dir", lambda: None)
    activity = collect_radar_activity(since=date(2026, 6, 23), until=date(2026, 6, 23))
    assert activity == {"briefings": [], "briefing_count": 0, "feed_files": []}


def test__distill_radar_activity_raw_fallback_no_api():
    """synthesize=False must not call any API and must return entry fields."""
    activity = {
        "briefings": [{"when": "2026-06-23 16:00", "text": "TOP 3: ship it"}],
        "briefing_count": 1,
        "feed_files": [],
    }
    d = distill_radar_activity(activity, synthesize=False)
    assert d["skip"] is False
    assert d["synthesized"] is False
    assert "1 DAILY RADAR briefing" in d["moment"]
    for key in ("moment", "what_happened", "possible_use", "tags"):
        assert key in d
