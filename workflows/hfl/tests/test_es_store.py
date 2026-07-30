"""
Tests for workflows/hfl/es_store.py.

Elasticsearch calls are intercepted — no live service is required.
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
        entry_id="hfl-test-entry",
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
    assert captured["id"] == "hfl-test-entry"
    d = captured["doc"]
    assert d["source"] == "git"
    assert d["moment"] == "Wired the ES store"
    assert d["entry_date"] == "2026-05-17"
    assert d["tags"] == ["hfl", "elasticsearch"]
    assert d["references"] == ["https://example.com/x"]
    assert d["synthesized"] is True


def test__index_uses_canonical_id_across_calls(monkeypatch):
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


def test__index_without_canonical_id_is_rejected(monkeypatch):
    called = {"n": 0}
    monkeypatch.setattr(
        "core.apps.es_logging.app.elasticsearch.post",
        lambda *a, **k: called.update(n=called["n"] + 1),
    )
    entry = HflEntry(when=datetime(2026, 5, 17), moment="No id")

    assert es.index_hfl_entry(entry, source="git") is None
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

def test__query_builds_filtered_body_and_uses_es_sort(monkeypatch):
    captured = {}

    def fake_search(body):
        captured["body"] = body
        return [
            {"entry_date": "2026-05-17", "moment": "newer"},
            {"entry_date": "2026-05-10", "moment": "older"},
        ]

    monkeypatch.setattr(es, "_search", fake_search)
    rows = es.query_hfl_entries(
        query="celery", since="2026-05-01", until="2026-05-31",
        tags=["#hfl"], source="git", limit=5,
    )
    assert [r["moment"] for r in rows] == ["newer", "older"]  # newest first
    body = captured["body"]
    assert body["size"] == 5
    assert body["sort"] == [
        {"_score": "desc"}, {"when": "desc"}, {"entry_id": "asc"}
    ]
    b = body["query"]["bool"]
    assert any("multi_match" in m for m in b["must"])
    assert any(
        {"term": {"tags": "hfl"}} in item["bool"]["should"]
        for item in b["filter"] if "bool" in item
    )
    assert any(
        {"term": {"source": "git"}} in item["bool"]["should"]
        for item in b["filter"] if "bool" in item
    )
    assert any("range" in f for f in b["filter"])


def test__query_empty_filters_use_match_all(monkeypatch):
    captured = {}

    def fake_search(body):
        captured["body"] = body
        return []

    monkeypatch.setattr(es, "_search", fake_search)

    assert es.query_hfl_entries() == []
    assert captured["body"]["sort"] == [
        {"when": "desc"}, {"entry_id": "asc"}
    ]


def test__query_retries_legacy_entry_id_keyword_mapping(monkeypatch):
    sorts = []

    def fake_search(body):
        sorts.append(body["sort"])
        if len(sorts) == 1:
            raise RuntimeError("Fielddata is disabled on [entry_id]")
        return [{"moment": "legacy mapping result"}]

    monkeypatch.setattr(es, "_search", fake_search)

    result = es.query_hfl_entries_status(source="youtube")

    assert result.available is True
    assert result.rows == ({"moment": "legacy mapping result"},)
    assert sorts == [
        [{"when": "desc"}, {"entry_id": "asc"}],
        [{"when": "desc"}, {"entry_id.keyword": "asc"}],
    ]


def test__query_swallows_failure(monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("search failed")

    monkeypatch.setattr(es, "_search", boom)
    assert es.query_hfl_entries(query="x") == []
    result = es.query_hfl_entries_status(query="x")
    assert result.available is False
    assert result.error == "elasticsearch_unavailable"
