"""Tests for the win32-free DAILY RADAR collector (workflows/hud/collectors/daily_radar).

The Claude synthesis call is stubbed and no sources are pulled, so these run
fully offline — they exercise the collector's wiring (input gather → prompt →
dump composition → metrics → return shape), not the live APIs. The live
end-to-end path is covered by workflows/hud/tests/test_hud_radar.py::test__show_daily_radar.
"""
import workflows.hud.collectors.daily_radar as collector
from workflows.hud.collectors.daily_radar import collect_daily_radar


def test__collect_daily_radar_offline_shape(monkeypatch):
    """With Claude stubbed and no sources, the collector returns the canonical
    {text, summary, metrics, links} payload and never touches the network."""
    monkeypatch.setattr(collector, "_run_claude_synthesis", lambda **_: "TEST BRIEFING BODY")

    out = collect_daily_radar(sources=[], desktop_dump_path=None, model="claude-haiku-4-5-20251001")

    assert isinstance(out, dict)
    # dump carries the briefing wrapped in the [START]/[END] window bookends
    assert "TEST BRIEFING BODY" in out["text"]
    assert "[START]" in out["text"] and "[END]" in out["text"]
    # summary + metrics are present and reflect the (empty) source set
    assert out["summary"].startswith("daily radar")
    assert out["metrics"]["sources_active"] == []
    assert out["metrics"]["model"] == "claude-haiku-4-5-20251001"
    # host twin omits the desktop dump → recorded as None in links
    assert out["links"]["desktop_logs_dump"] is None


def test__collect_daily_radar_passes_window_to_bookends(monkeypatch):
    """window_hours flows through to the [START]/[END] range, not just the API."""
    monkeypatch.setattr(collector, "_run_claude_synthesis", lambda **_: "BODY")
    out = collect_daily_radar(sources=[], desktop_dump_path=None, window_hours=2)
    assert out["metrics"]["window_hours"] == 2
    assert "window 2h" in out["summary"]
