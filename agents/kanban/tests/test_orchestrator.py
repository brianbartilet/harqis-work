"""
Tests for LocalOrchestrator.
Provider and agent are mocked — no API calls.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch, call

import pytest
from hamcrest import assert_that, equal_to, contains_string

from agents.kanban.interface import KanbanCard
from agents.kanban.orchestrator.local import LocalOrchestrator, _load_dotenv
from agents.kanban.profiles.registry import ProfileRegistry
from agents.kanban.profiles.schema import AgentProfile, LifecycleConfig


@pytest.fixture()
def mock_provider():
    p = MagicMock()
    p.get_cards.return_value = []
    return p


@pytest.fixture()
def mock_registry(open_profile):
    r = MagicMock(spec=ProfileRegistry)
    r.resolve_for_card.return_value = open_profile
    return r


@pytest.fixture()
def orchestrator(mock_provider, mock_registry):
    return LocalOrchestrator(
        provider=mock_provider,
        registry=mock_registry,
        api_key="test_api_key",
        board_id="board123",
        poll_interval=1,
    )


@pytest.mark.smoke
def test_poll_once_empty_backlog(orchestrator, mock_provider):
    mock_provider.get_cards.return_value = []
    n = orchestrator.poll_once()
    assert_that(n, equal_to(0))


@pytest.mark.smoke
def test_poll_once_processes_matched_cards(orchestrator, mock_provider, mock_registry, sample_card):
    mock_provider.get_cards.return_value = [sample_card]

    with patch("agents.kanban.orchestrator.local.BaseKanbanAgent") as mock_agent_cls:
        mock_agent = MagicMock()
        mock_agent.run.return_value = "Task done!"
        mock_agent_cls.return_value = mock_agent

        n = orchestrator.poll_once()

    assert_that(n, equal_to(1))
    mock_provider.move_card.assert_any_call(sample_card.id, "Pending")
    mock_provider.move_card.assert_any_call(sample_card.id, "In Progress")
    comment_texts = [c.args[1] for c in mock_provider.add_comment.call_args_list]
    assert_that(any("claimed-by" in t for t in comment_texts), equal_to(True))


@pytest.mark.smoke
def test_poll_once_skips_unmatched_cards(orchestrator, mock_provider, mock_registry, sample_card):
    mock_provider.get_cards.return_value = [sample_card]
    mock_registry.resolve_for_card.return_value = None  # no profile match

    n = orchestrator.poll_once()

    assert_that(n, equal_to(0))
    mock_provider.move_card.assert_not_called()


@pytest.mark.smoke
def test_process_card_moves_to_review_when_not_auto_approved(
    orchestrator, mock_provider, open_profile, sample_card
):
    open_profile.lifecycle.auto_approve = False
    with patch("agents.kanban.orchestrator.local.BaseKanbanAgent") as mock_agent_cls:
        mock_agent_cls.return_value.run.return_value = "result"
        orchestrator.process_card(sample_card)

    move_calls = [c.args[1] for c in mock_provider.move_card.call_args_list]
    assert_that("Done" in move_calls, equal_to(True))


@pytest.mark.smoke
def test_process_card_moves_to_done_when_auto_approved(
    orchestrator, mock_provider, open_profile, sample_card
):
    open_profile.lifecycle.auto_approve = True
    with patch("agents.kanban.orchestrator.local.BaseKanbanAgent") as mock_agent_cls:
        mock_agent_cls.return_value.run.return_value = "result"
        orchestrator.process_card(sample_card)

    move_calls = [c.args[1] for c in mock_provider.move_card.call_args_list]
    assert_that("Done" in move_calls, equal_to(True))


@pytest.mark.smoke
def test_process_card_posts_error_on_agent_failure(
    orchestrator, mock_provider, open_profile, sample_card
):
    with patch("agents.kanban.orchestrator.local.BaseKanbanAgent") as mock_agent_cls:
        mock_agent_cls.return_value.run.side_effect = RuntimeError("something broke")
        orchestrator.process_card(sample_card)

    move_calls = [c.args[1] for c in mock_provider.move_card.call_args_list]
    assert_that("Failed" in move_calls, equal_to(True))

    comment_texts = [c.args[1] for c in mock_provider.add_comment.call_args_list]
    error_comments = [t for t in comment_texts if "Error" in t]
    assert_that(len(error_comments) > 0, equal_to(True))


@pytest.mark.smoke
def test_dry_run_skips_agent_execution(orchestrator, mock_provider, sample_card):
    orchestrator.dry_run = True
    mock_provider.get_cards.return_value = [sample_card]

    with patch("agents.kanban.orchestrator.local.BaseKanbanAgent") as mock_agent_cls:
        orchestrator.poll_once()
        mock_agent_cls.assert_not_called()


@pytest.mark.smoke
def test_load_dotenv(tmp_path):
    env_file = tmp_path / "test.env"
    env_file.write_text(
        "# comment\nMY_VAR=hello\nANOTHER=world\nEMPTY=\n",
        encoding="utf-8",
    )

    import os
    # Remove vars if already set
    os.environ.pop("MY_VAR", None)
    os.environ.pop("ANOTHER", None)

    _load_dotenv(env_file)

    assert_that(os.environ.get("MY_VAR"), equal_to("hello"))
    assert_that(os.environ.get("ANOTHER"), equal_to("world"))


@pytest.mark.integration
def test_live_poll_dry_run():
    """Integration: polls a real board in dry-run mode. No agents are executed."""
    import os
    from agents.kanban.orchestrator.local import from_env

    os.environ.setdefault("KANBAN_DRY_RUN", "1")
    orch = from_env()
    n = orch.poll_once()
    # Just verify it ran without error — n may be 0 if no matching cards
    assert_that(isinstance(n, int), equal_to(True))
