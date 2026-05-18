"""
Tests for workflows/hfl/tasks/ingest_browsing.py.

Integration tests call the real task exactly as Beat will. The default
(no Chrome/Edge History DB found) is a guaranteed no-op — no LLM, no
side-effects. The live path (real Anthropic synthesis + corpus/ES write)
is marked skip. Unit tests build a throwaway Chromium-shaped SQLite DB so
the collector/parse helpers run without a browser.
"""

import sqlite3
from datetime import date, datetime, timedelta

import pytest

from workflows.hfl.tasks.ingest_browsing import (
    _CHROME_EPOCH_OFFSET,
    _activity_body,
    _domain,
    _from_chrome_time,
    _to_chrome_time,
    _top_references,
    collect_browsing_activity,
    distill_browsing_activity,
    ingest_browsing_activity,
)


def _make_history_db(path, rows):
    """rows: list of (url, title, visit_count, when:datetime)."""
    conn = sqlite3.connect(str(path))
    conn.executescript(
        """
        CREATE TABLE urls(id INTEGER PRIMARY KEY, url TEXT, title TEXT,
                          visit_count INTEGER);
        CREATE TABLE visits(id INTEGER PRIMARY KEY, url INTEGER,
                            visit_time INTEGER);
        """
    )
    for i, (url, title, vc, when) in enumerate(rows, start=1):
        conn.execute(
            "INSERT INTO urls(id,url,title,visit_count) VALUES(?,?,?,?)",
            (i, url, title, vc),
        )
        conn.execute(
            "INSERT INTO visits(id,url,visit_time) VALUES(?,?,?)",
            (i, i, _to_chrome_time(when)),
        )
    conn.commit()
    conn.close()


# ── Workflow (integration) ────────────────────────────────────────────────────

def test__ingest_browsing_activity_no_history_db(monkeypatch):
    """No Chrome/Edge DB → clean no-op, no LLM, no corpus write."""
    monkeypatch.setenv("HFL_BROWSING_CHROME_HISTORY", "/nope/Chrome/History")
    monkeypatch.setenv("HFL_BROWSING_EDGE_HISTORY", "/nope/Edge/History")
    monkeypatch.setenv("LOCALAPPDATA", "")
    result = ingest_browsing_activity(cfg_id__anthropic="ANTHROPIC")
    assert result["entries_written"] == 0
    assert result["skipped"] == "no history db"


def test__ingest_browsing_activity_dual_write_contract(monkeypatch, tmp_path):
    """A real in-window visit must drive BOTH the corpus write and the ES
    index call (the mandatory dual-write contract)."""
    db = tmp_path / "History"
    _make_history_db(
        db,
        [("https://docs.celeryq.dev/beat", "Celery beat", 5, datetime.now())],
    )
    monkeypatch.setenv("HFL_BROWSING_CHROME_HISTORY", str(db))
    monkeypatch.setenv("HFL_BROWSING_EDGE_HISTORY", "/nope/Edge/History")

    # Hermetic: no Anthropic call, corpus into tmp, capture the ES write.
    monkeypatch.setattr(
        "workflows.hfl.tasks.ingest_browsing.distill_browsing_activity",
        lambda activity, **kw: {
            "skip": False, "moment": "browsed celery docs",
            "what_happened": "read beat docs", "why_it_stayed": "",
            "possible_use": "research-log", "tags": ["celery"],
            "synthesized": False,
        },
    )
    monkeypatch.setattr(
        "workflows.hfl.tasks.ingest_browsing.resolve_corpus_dir",
        lambda: tmp_path,
    )
    indexed = []
    monkeypatch.setattr(
        "workflows.hfl.tasks.capture.index_hfl_entry",
        lambda entry, *, source, synthesized=False: indexed.append(source)
        or "doc-1",
    )

    result = ingest_browsing_activity(cfg_id__anthropic="ANTHROPIC")
    assert result["entries_written"] == 1
    assert result["indexed"] is True
    assert indexed == ["browsing"]  # ES dual-write happened
    written = (tmp_path / f"{datetime.now():%Y-%m-%d}.md").read_text(
        encoding="utf-8"
    )
    assert "browsed celery docs" in written  # corpus write happened


@pytest.mark.skip(reason="Manual only — reads the live local Chrome/Edge "
                         "history + real Anthropic synthesis; appends a real "
                         "entry to today's corpus and the ES index.")
def test__ingest_browsing_activity_full_pipeline():
    result = ingest_browsing_activity(cfg_id__anthropic="ANTHROPIC", window_days=1)
    assert result["entries_written"] in (0, 1)


# ── Unit / function ───────────────────────────────────────────────────────────

def test__chrome_time_roundtrips():
    dt = datetime(2026, 5, 17, 9, 30, 0)
    assert abs((_from_chrome_time(_to_chrome_time(dt)) - dt).total_seconds()) < 1
    # Sanity on the epoch offset constant.
    assert _CHROME_EPOCH_OFFSET == 11_644_473_600


def test__domain_strips_www_and_handles_garbage():
    assert _domain("https://www.youtube.com/watch?v=x") == "youtube.com"
    assert _domain("https://docs.celeryq.dev/a/b") == "docs.celeryq.dev"
    assert _domain("not a url") == ""


def test__collect_browsing_windows_and_aggregates(tmp_path, monkeypatch):
    db = tmp_path / "History"
    now = datetime.now()
    _make_history_db(db, [
        ("https://a.com/1", "A one", 3, now),
        ("https://a.com/2", "A two", 1, now),
        ("https://b.com/x", "B x", 9, now),
        ("https://old.com/", "Old", 1, now - timedelta(days=900)),
    ])
    monkeypatch.setenv("HFL_BROWSING_CHROME_HISTORY", str(db))
    monkeypatch.setenv("HFL_BROWSING_EDGE_HISTORY", "/nope/Edge/History")

    act = collect_browsing_activity(
        since=date.today() - timedelta(days=1), until=date.today(),
        browsers=("chrome",),
    )
    assert act["history_found"] is True
    assert act["visit_count"] == 3            # the 900-day-old row excluded
    assert act["domains"][0]["domain"] == "a.com"  # 2 visits, busiest first
    assert "chrome" in act["browsers_read"]


def test__collect_browsing_exclude_domains(tmp_path, monkeypatch):
    db = tmp_path / "History"
    now = datetime.now()
    _make_history_db(db, [
        ("https://keep.com/1", "K", 1, now),
        ("https://bank.example/secret", "B", 1, now),
    ])
    monkeypatch.setenv("HFL_BROWSING_CHROME_HISTORY", str(db))
    monkeypatch.setenv("HFL_BROWSING_EDGE_HISTORY", "/nope/Edge/History")
    act = collect_browsing_activity(
        since=date.today() - timedelta(days=1), until=date.today(),
        browsers=("chrome",), exclude_domains=("bank.example",),
    )
    assert act["visit_count"] == 1
    assert {d["domain"] for d in act["domains"]} == {"keep.com"}


def test__activity_body_and_top_references():
    activity = {
        "domains": [{"domain": "a.com", "visits": 2, "top_title": "A one"}],
        "visits": [
            {"when": "2026-05-17 09:00", "url": "https://a.com/1",
             "domain": "a.com", "title": "A one", "visit_count": 7},
            {"when": "2026-05-17 09:05", "url": "https://a.com/2",
             "domain": "a.com", "title": "A two", "visit_count": 1},
        ],
    }
    body = _activity_body(activity)
    assert "a.com" in body and "A one" in body
    refs = _top_references(activity)
    assert refs[0] == "https://a.com/1"  # highest visit_count first


def test__distill_browsing_raw_fallback_no_api():
    """synthesize=False must not call any API and must return entry fields."""
    activity = {
        "domains": [{"domain": "a.com", "visits": 3, "top_title": "A"}],
        "visits": [], "visit_count": 3, "domain_count": 1,
        "browsers_read": ["chrome"],
    }
    d = distill_browsing_activity(activity, synthesize=False)
    assert d["skip"] is False
    assert d["synthesized"] is False
    assert "3 page visit" in d["moment"]
    for key in ("moment", "what_happened", "possible_use", "tags"):
        assert key in d
