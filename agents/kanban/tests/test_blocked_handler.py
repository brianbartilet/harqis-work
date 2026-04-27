"""
Tests for agents/kanban/orchestrator/blocked_handler.py

Provider is mocked — no API calls.
"""

from __future__ import annotations

import os
from unittest.mock import MagicMock, call, patch

import pytest
from hamcrest import assert_that, equal_to

from agents.kanban.interface import KanbanCard
from agents.kanban.orchestrator.blocked_handler import BlockedCardHandler


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture()
def mock_provider():
    p = MagicMock()
    p.get_cards.return_value = []
    return p


@pytest.fixture()
def handler(mock_provider):
    return BlockedCardHandler(provider=mock_provider, board_id="board123")


def _blocked_card(card_id: str = "c1", custom_fields: dict | None = None) -> KanbanCard:
    return KanbanCard(
        id=card_id,
        title=f"Blocked card {card_id}",
        description="Some task",
        labels=["agent:full"],
        assignees=[],
        column="Blocked",
        url=f"https://trello.com/c/{card_id}",
        custom_fields=custom_fields or {},
    )


# ── poll_once — empty column ──────────────────────────────────────────────────

@pytest.mark.smoke
def test_poll_once_empty_blocked_column(handler, mock_provider):
    mock_provider.get_cards.return_value = []
    n = handler.poll_once()
    assert_that(n, equal_to(0))
    mock_provider.move_card.assert_not_called()


# ── poll_once — card with no explicit deps (should be re-queued) ──────────────

@pytest.mark.smoke
def test_poll_once_requeues_card_with_no_deps(handler, mock_provider):
    card = _blocked_card()
    mock_provider.get_cards.return_value = [card]
    n = handler.poll_once()
    assert_that(n, equal_to(1))
    mock_provider.move_card.assert_called_once_with(card.id, "Backlog")


@pytest.mark.smoke
def test_poll_once_posts_comment_when_requeuing(handler, mock_provider):
    card = _blocked_card()
    mock_provider.get_cards.return_value = [card]
    handler.poll_once()
    comment_texts = [c.args[1] for c in mock_provider.add_comment.call_args_list]
    assert any("Dependencies Resolved" in t for t in comment_texts)


# ── poll_once — card with blocking dep still missing ─────────────────────────

@pytest.mark.smoke
def test_poll_once_leaves_card_blocked_when_secret_missing(handler, mock_provider):
    card = _blocked_card(custom_fields={"required_secrets": "STILL_MISSING_KEY_XYZ"})
    mock_provider.get_cards.return_value = [card]
    env = {k: v for k, v in os.environ.items() if k != "STILL_MISSING_KEY_XYZ"}
    with patch.dict(os.environ, env, clear=True):
        n = handler.poll_once()
    assert_that(n, equal_to(0))
    mock_provider.move_card.assert_not_called()


# ── poll_once — card with blocking dep now present ────────────────────────────

@pytest.mark.smoke
def test_poll_once_requeues_when_secret_now_present(handler, mock_provider):
    card = _blocked_card(custom_fields={"required_secrets": "NOW_PRESENT_KEY"})
    mock_provider.get_cards.return_value = [card]
    with patch.dict(os.environ, {"NOW_PRESENT_KEY": "secret-value"}, clear=False):
        n = handler.poll_once()
    assert_that(n, equal_to(1))
    mock_provider.move_card.assert_called_once_with(card.id, "Backlog")


# ── poll_once — multiple cards mixed state ────────────────────────────────────

@pytest.mark.smoke
def test_poll_once_mixed_cards(handler, mock_provider):
    resolved_card = _blocked_card("c1")
    still_blocked = _blocked_card("c2", custom_fields={"required_secrets": "MISSING_FOREVER_XYZ"})
    mock_provider.get_cards.return_value = [resolved_card, still_blocked]
    env = {k: v for k, v in os.environ.items() if k != "MISSING_FOREVER_XYZ"}
    with patch.dict(os.environ, env, clear=True):
        n = handler.poll_once()
    assert_that(n, equal_to(1))
    move_calls = [c.args for c in mock_provider.move_card.call_args_list]
    assert ("c1", "Backlog") in move_calls
    assert not any(a[0] == "c2" for a in move_calls)


# ── Provider error handling ───────────────────────────────────────────────────

@pytest.mark.smoke
def test_poll_once_handles_provider_error_gracefully(handler, mock_provider):
    mock_provider.get_cards.side_effect = RuntimeError("network error")
    n = handler.poll_once()
    assert_that(n, equal_to(0))


@pytest.mark.smoke
def test_poll_once_continues_after_single_card_error(handler, mock_provider):
    good_card = _blocked_card("good")
    mock_provider.get_cards.return_value = [good_card]
    mock_provider.add_comment.side_effect = [RuntimeError("comment failed")]
    # Even if requeue fails for one card, it shouldn't crash the handler
    n = handler.poll_once()
    # add_comment raised, so move_card was never called → n = 0
    assert_that(n, equal_to(0))
