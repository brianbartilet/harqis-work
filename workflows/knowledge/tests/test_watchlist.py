"""Watchlist YAML loader."""

from pathlib import Path

import pytest

from workflows.knowledge.watchlist import (
    load_watchlists,
    get_watchlist,
    all_services,
)

_FIXTURE = Path(__file__).parent / "_watchlists_fixture.yaml"


@pytest.fixture(autouse=True)
def _write_fixture():
    _FIXTURE.write_text(
        """
watchlists:
  - id: wl-a
    title: Watchlist A
    sources: [confluence, jira]
    keywords: [alpha, beta]
    services: [Payments, Ledger]
    semantic_prompt: Surface alpha and beta things.
    cadence: daily
  - id: wl-b
    title: Watchlist B
    services: [Ledger, FraudCheck]
""".strip(),
        encoding="utf-8",
    )
    yield
    _FIXTURE.unlink(missing_ok=True)


def test_load_parses_all():
    wls = load_watchlists(_FIXTURE)
    assert [w.id for w in wls] == ["wl-a", "wl-b"]


def test_query_text_combines_prompt_and_keywords():
    wl = get_watchlist("wl-a", _FIXTURE)
    assert "alpha and beta things" in wl.query_text
    assert "alpha, beta" in wl.query_text


def test_all_services_is_deduped_union():
    services = all_services(_FIXTURE)
    assert services == ["Payments", "Ledger", "FraudCheck"]  # order-stable, deduped


def test_unknown_id_returns_none():
    assert get_watchlist("nope", _FIXTURE) is None


def test_missing_file_returns_empty():
    assert load_watchlists(Path("does-not-exist.yaml")) == []
