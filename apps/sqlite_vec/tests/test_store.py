"""Smoke tests for apps/sqlite_vec/store.py — no network, no API keys."""

from pathlib import Path

import pytest

try:
    import sqlite_vec  # noqa: F401
except ImportError:
    pytest.skip("sqlite-vec is not installed — skipping vector store tests", allow_module_level=True)

from apps.sqlite_vec import store


@pytest.fixture
def tmp_db(tmp_path: Path) -> Path:
    return tmp_path / "vec.db"


def test_upsert_and_search_returns_nearest(tmp_db: Path):
    store.upsert("a", "alpha", [1.0, 0.0, 0.0], source="t", db_path=tmp_db)
    store.upsert("b", "beta",  [0.0, 1.0, 0.0], source="t", db_path=tmp_db)
    store.upsert("c", "gamma", [0.0, 0.0, 1.0], source="t", db_path=tmp_db)

    hits = store.search([1.0, 0.05, 0.0], k=2, db_path=tmp_db)
    assert len(hits) == 2
    assert hits[0]["id"] == "a"
    assert hits[0]["text"] == "alpha"
    assert hits[0]["distance"] <= hits[1]["distance"]


def test_upsert_replaces_existing_row(tmp_db: Path):
    store.upsert("a", "v1", [1.0, 0.0], source="t", db_path=tmp_db)
    store.upsert("a", "v2", [1.0, 0.0], source="t", db_path=tmp_db)

    hits = store.search([1.0, 0.0], k=5, db_path=tmp_db)
    assert len(hits) == 1
    assert hits[0]["text"] == "v2"


def test_search_filters_by_source(tmp_db: Path):
    store.upsert("a", "from-notion", [1.0, 0.0], source="notion", db_path=tmp_db)
    store.upsert("b", "from-jira",   [1.0, 0.01], source="jira",   db_path=tmp_db)

    hits = store.search([1.0, 0.0], k=5, source="notion", db_path=tmp_db)
    assert len(hits) == 1
    assert hits[0]["source"] == "notion"


def test_delete_by_source_removes_only_that_source(tmp_db: Path):
    store.upsert("a", "x", [1.0, 0.0], source="notion", db_path=tmp_db)
    store.upsert("b", "y", [0.0, 1.0], source="jira",   db_path=tmp_db)

    n = store.delete_by_source("notion", db_path=tmp_db)
    assert n == 1

    s = store.stats(db_path=tmp_db)
    assert s["total"] == 1
    assert "notion" not in s["by_source"]


def test_meta_roundtrips(tmp_db: Path):
    store.upsert(
        "a", "x", [1.0, 0.0],
        source="notion",
        ref="https://notion.so/foo",
        meta={"page_id": "abc", "chunk_idx": 3},
        db_path=tmp_db,
    )
    hits = store.search([1.0, 0.0], k=1, db_path=tmp_db)
    assert hits[0]["ref"] == "https://notion.so/foo"
    assert hits[0]["meta"] == {"page_id": "abc", "chunk_idx": 3}
