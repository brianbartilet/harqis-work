"""
Tests for workflows/hfl/es_store.py.

es_logging.post / get_index_data are mocked — no live Elasticsearch. The
contract under test: deterministic dedup id, correct doc shape, empty-
moment no-op, and that every ES failure is swallowed (write returns None,
read returns []) so the beat / MCP never break.
"""

from datetime import datetime

import workflows.hfl.es_store as es
from workflows.hfl.dto import HflEntry


def _entry(moment="Wired the ES store", when=datetime(2026, 5, 17, 23, 0)):
    return HflEntry(
        when=when,
        moment=moment,
        what_happened="Added index + query helpers.",
        why_it_stayed="Closes the dual-write loop.",
        possible_use="portfolio",
        tags=("hfl", "elasticsearch"),
        references=("https://example.com/x",),
    )


# ── index_hfl_entry ───────────────────────────────────────────────────────────

def test__index_posts_expected_doc_and_deterministic_id(monkeypatch):
    captured = {}

    def fake_post(json_dump, index_name, location_key, use_interval_map=True,
                  identifier="", update_interval=None):
        captured["doc"] = json_dump
        captured["index"] = index_name
        captured["id"] = location_key
        captured["use_interval_map"] = use_interval_map

    monkeypatch.setattr(
        "core.apps.es_logging.app.elasticsearch.post", fake_post
    )
    doc_id = es.index_hfl_entry(_entry(), source="git", synthesized=True)

    assert doc_id == captured["id"]
    assert captured["use_interval_map"] is False
    assert captured["index"] == "harqis-hfl-entries"
    assert captured["id"].startswith("20260517-git-")
    d = captured["doc"]
    assert d["source"] == "git"
    assert d["moment"] == "Wired the ES store"
    assert d["entry_date"] == "2026-05-17"
    assert d["tags"] == ["hfl", "elasticsearch"]
    assert d["references"] == ["https://example.com/x"]
    assert d["synthesized"] is True


def test__index_id_is_stable_across_calls(monkeypatch):
    monkeypatch.setattr(
        "core.apps.es_logging.app.elasticsearch.post", lambda *a, **k: None
    )
    a = es.index_hfl_entry(_entry(), source="git")
    b = es.index_hfl_entry(_entry(), source="git")
    assert a == b  # same content → same id → upsert, no dupes


def test__index_empty_moment_is_noop(monkeypatch):
    called = {"n": 0}

    def fake_post(*a, **k):
        called["n"] += 1

    monkeypatch.setattr(
        "core.apps.es_logging.app.elasticsearch.post", fake_post
    )
    assert es.index_hfl_entry(_entry(moment="   "), source="git") is None
    assert called["n"] == 0


def test__index_swallows_es_failure(monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("ES down")

    monkeypatch.setattr(
        "core.apps.es_logging.app.elasticsearch.post", boom
    )
    # Must NOT raise — corpus write already succeeded upstream.
    assert es.index_hfl_entry(_entry(), source="git") is None


def test__index_honours_HFL_ES_INDEX_env(monkeypatch):
    seen = {}
    monkeypatch.setenv("HFL_ES_INDEX", "custom-hfl")
    monkeypatch.setattr(
        "core.apps.es_logging.app.elasticsearch.post",
        lambda doc, index_name, **k: seen.update(i=index_name),
    )
    es.index_hfl_entry(_entry(), source="git")
    assert seen["i"] == "custom-hfl"


# ── query_hfl_entries ─────────────────────────────────────────────────────────

def test__query_builds_filtered_body_and_sorts(monkeypatch):
    captured = {}

    def fake_get(index_name, query=None, fetch_docs=10000, **k):
        captured["index"] = index_name
        captured["query"] = query
        captured["fetch"] = fetch_docs
        return [
            {"entry_date": "2026-05-10", "moment": "older"},
            {"entry_date": "2026-05-17", "moment": "newer"},
        ]

    monkeypatch.setattr(
        "core.apps.es_logging.app.elasticsearch.get_index_data", fake_get
    )
    rows = es.query_hfl_entries(
        query="celery", since="2026-05-01", until="2026-05-31",
        tags=["#hfl"], source="git", limit=5,
    )
    assert [r["moment"] for r in rows] == ["newer", "older"]  # newest first
    assert captured["index"] == "harqis-hfl-entries"
    assert captured["fetch"] == 5
    b = captured["query"]["bool"]
    assert any("multi_match" in m for m in b["must"])
    assert {"term": {"tags": "hfl"}} in b["filter"]
    assert {"term": {"source": "git"}} in b["filter"]
    assert any("range" in f for f in b["filter"])


def test__query_empty_filters_use_match_all(monkeypatch):
    monkeypatch.setattr(
        "core.apps.es_logging.app.elasticsearch.get_index_data",
        lambda *a, **k: [],
    )
    assert es.query_hfl_entries() == []


def test__query_swallows_failure(monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("search failed")

    monkeypatch.setattr(
        "core.apps.es_logging.app.elasticsearch.get_index_data", boom
    )
    assert es.query_hfl_entries(query="x") == []
