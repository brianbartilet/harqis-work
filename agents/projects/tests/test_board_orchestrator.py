"""
Tests for BoardOrchestrator — single-board polling + agent dispatch.
TrelloClient and the agent class are mocked — no API calls.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from hamcrest import assert_that, equal_to

from agents.projects.orchestrator.board import BoardOrchestrator
from agents.projects.orchestrator.lists import Lists
from agents.projects.orchestrator.local import _load_dotenv
from agents.projects.profiles.registry import ProfileRegistry
from agents.projects.security.secret_store import SecretStore
from agents.projects.trello.models import KanbanCard


@pytest.fixture()
def mock_client():
    c = MagicMock()
    c.get_cards.return_value = []
    return c


@pytest.fixture()
def mock_registry(open_profile):
    r = MagicMock(spec=ProfileRegistry)
    r.resolve_for_card.return_value = open_profile
    return r


@pytest.fixture()
def orchestrator(mock_client, mock_registry):
    return BoardOrchestrator(
        client=mock_client,
        registry=mock_registry,
        api_key="test_api_key",
        board_id="board123",
        secret_store=SecretStore(),
        audit_log_path=Path("logs/test_audit.jsonl"),
        os_labels=set(),  # routing disabled for these tests
        profile_filter=None,
    )


@pytest.mark.smoke
def test_poll_intake_empty_returns_zero(orchestrator, mock_client):
    mock_client.get_cards.return_value = []
    n = orchestrator.poll_intake()
    assert_that(n, equal_to(0))


@pytest.mark.smoke
def test_poll_intake_processes_matched_cards(orchestrator, mock_client, sample_card):
    mock_client.get_cards.return_value = [sample_card]

    with patch("agents.projects.orchestrator.board.BaseKanbanAgent") as mock_agent_cls:
        mock_agent = MagicMock()
        mock_agent.run.return_value = "Task done!"
        mock_agent_cls.return_value = mock_agent

        n = orchestrator.poll_intake()

    assert_that(n, equal_to(1))
    mock_client.move_card.assert_any_call(sample_card.id, Lists.PENDING)
    mock_client.move_card.assert_any_call(sample_card.id, Lists.IN_PROGRESS)
    comment_texts = [c.args[1] for c in mock_client.add_comment.call_args_list]
    assert_that(any("claimed-by" in t for t in comment_texts), equal_to(True))


@pytest.mark.smoke
def test_poll_intake_skips_unmatched_cards(orchestrator, mock_client, mock_registry, sample_card):
    mock_client.get_cards.return_value = [sample_card]
    mock_registry.resolve_for_card.return_value = None

    n = orchestrator.poll_intake()

    assert_that(n, equal_to(0))
    mock_client.move_card.assert_not_called()


@pytest.mark.smoke
def test_process_card_moves_to_in_review_when_not_auto_approved(
    orchestrator, mock_client, open_profile, sample_card
):
    """Default flow: agent finishes → In Review (awaiting human approval)."""
    open_profile.lifecycle.auto_approve = False
    with patch("agents.projects.orchestrator.board.BaseKanbanAgent") as mock_agent_cls:
        mock_agent_cls.return_value.run.return_value = "result"
        orchestrator.process_card(sample_card)

    move_calls = [c.args[1] for c in mock_client.move_card.call_args_list]
    assert_that(Lists.IN_REVIEW in move_calls, equal_to(True))
    assert_that(Lists.DONE in move_calls, equal_to(False))


@pytest.mark.smoke
def test_process_card_moves_to_done_when_auto_approved(
    orchestrator, mock_client, open_profile, sample_card
):
    """Auto-approve profiles skip In Review and land directly in Done."""
    open_profile.lifecycle.auto_approve = True
    with patch("agents.projects.orchestrator.board.BaseKanbanAgent") as mock_agent_cls:
        mock_agent_cls.return_value.run.return_value = "result"
        orchestrator.process_card(sample_card)

    move_calls = [c.args[1] for c in mock_client.move_card.call_args_list]
    assert_that(Lists.DONE in move_calls, equal_to(True))
    assert_that(Lists.IN_REVIEW in move_calls, equal_to(False))


@pytest.mark.smoke
def test_process_card_posts_error_on_agent_failure(
    orchestrator, mock_client, open_profile, sample_card
):
    with patch("agents.projects.orchestrator.board.BaseKanbanAgent") as mock_agent_cls:
        mock_agent_cls.return_value.run.side_effect = RuntimeError("something broke")
        orchestrator.process_card(sample_card)

    move_calls = [c.args[1] for c in mock_client.move_card.call_args_list]
    assert_that(Lists.FAILED in move_calls, equal_to(True))

    comment_texts = [c.args[1] for c in mock_client.add_comment.call_args_list]
    error_comments = [t for t in comment_texts if "Error" in t]
    assert_that(len(error_comments) > 0, equal_to(True))


@pytest.mark.smoke
def test_process_card_moves_to_failed_on_anthropic_usage_limit(
    orchestrator, mock_client, open_profile, sample_card
):
    """Regression: an Anthropic 400 'usage limit reached' must move the card
    to Failed (not In Review/Done) and surface the limit message."""
    from agents.projects.agent.base import AgentExecutionError

    msg = (
        "Error code: 400 - {'type': 'error', 'error': {'type': 'invalid_request_error', "
        "'message': 'You have reached your specified API usage limits. "
        "You will regain access on 2026-05-01 at 00:00 UTC.'}}"
    )
    with patch("agents.projects.orchestrator.board.BaseKanbanAgent") as mock_agent_cls:
        mock_agent_cls.return_value.run.side_effect = AgentExecutionError(
            msg, kind="api_usage_limit"
        )
        orchestrator.process_card(sample_card)

    final_destinations = [c.args[1] for c in mock_client.move_card.call_args_list]
    assert_that(Lists.FAILED in final_destinations, equal_to(True))
    assert_that(Lists.DONE not in final_destinations, equal_to(True))
    assert_that(Lists.IN_REVIEW not in final_destinations, equal_to(True))

    comments = [c.args[1] for c in mock_client.add_comment.call_args_list]
    assert_that(any("usage limit" in c.lower() for c in comments), equal_to(True))
    assert_that(any("2026-05-01" in c for c in comments), equal_to(True))


@pytest.mark.smoke
def test_process_card_moves_to_failed_on_anthropic_rate_limit(
    orchestrator, mock_client, open_profile, sample_card
):
    from agents.projects.agent.base import AgentExecutionError

    with patch("agents.projects.orchestrator.board.BaseKanbanAgent") as mock_agent_cls:
        mock_agent_cls.return_value.run.side_effect = AgentExecutionError(
            "Error code: 429 - rate_limit_exceeded", kind="api_rate_limit"
        )
        orchestrator.process_card(sample_card)

    destinations = [c.args[1] for c in mock_client.move_card.call_args_list]
    assert_that(Lists.FAILED in destinations, equal_to(True))
    comments = [c.args[1] for c in mock_client.add_comment.call_args_list]
    assert_that(any("rate limit" in c.lower() for c in comments), equal_to(True))


@pytest.mark.smoke
def test_dry_run_skips_agent_execution(orchestrator, mock_client, sample_card):
    orchestrator.dry_run = True
    mock_client.get_cards.return_value = [sample_card]

    with patch("agents.projects.orchestrator.board.BaseKanbanAgent") as mock_agent_cls:
        orchestrator.poll_intake()
        mock_agent_cls.assert_not_called()


@pytest.mark.smoke
def test_load_dotenv(tmp_path):
    env_file = tmp_path / "test.env"
    env_file.write_text(
        "# comment\nMY_VAR=hello\nANOTHER=world\nEMPTY=\n",
        encoding="utf-8",
    )

    import os
    os.environ.pop("MY_VAR", None)
    os.environ.pop("ANOTHER", None)

    _load_dotenv(env_file)

    assert_that(os.environ.get("MY_VAR"), equal_to("hello"))
    assert_that(os.environ.get("ANOTHER"), equal_to("world"))


@pytest.mark.smoke
def test_poll_intake_multi_agent_processes_all_cards(mock_client, mock_registry, sample_card):
    card2 = KanbanCard(
        id="card2", title="Second card", description="",
        labels=["agent:open"], assignees=[], column=Lists.READY, url="",
    )
    mock_client.get_cards.return_value = [sample_card, card2]

    orch = BoardOrchestrator(
        client=mock_client,
        registry=mock_registry,
        api_key="test_api_key",
        board_id="board123",
        secret_store=SecretStore(),
        audit_log_path=Path("logs/test_audit.jsonl"),
        os_labels=set(),
        profile_filter=None,
        num_agents=2,
    )

    with patch("agents.projects.orchestrator.board.BaseKanbanAgent") as mock_agent_cls:
        mock_agent_cls.return_value.run.return_value = "done"
        n = orch.poll_intake()

    assert_that(n, equal_to(2))


@pytest.mark.smoke
def test_num_agents_clamps_to_one_minimum(mock_client, mock_registry):
    orch = BoardOrchestrator(
        client=mock_client,
        registry=mock_registry,
        api_key="key",
        board_id="board",
        secret_store=SecretStore(),
        audit_log_path=Path("logs/test_audit.jsonl"),
        os_labels=set(),
        profile_filter=None,
        num_agents=0,
    )
    assert_that(orch.num_agents, equal_to(1))


@pytest.mark.smoke
def test_poll_intake_multi_agent_partial_failure(mock_client, mock_registry, sample_card):
    card2 = KanbanCard(
        id="card2", title="Failing card", description="",
        labels=["agent:open"], assignees=[], column=Lists.READY, url="",
    )
    mock_client.get_cards.return_value = [sample_card, card2]

    orch = BoardOrchestrator(
        client=mock_client,
        registry=mock_registry,
        api_key="test_api_key",
        board_id="board123",
        secret_store=SecretStore(),
        audit_log_path=Path("logs/test_audit.jsonl"),
        os_labels=set(),
        profile_filter=None,
        num_agents=2,
    )

    call_count = 0

    def run_side_effect():
        nonlocal call_count
        call_count += 1
        if call_count == 2:
            raise RuntimeError("agent exploded")
        return "done"

    with patch("agents.projects.orchestrator.board.BaseKanbanAgent") as mock_agent_cls:
        mock_agent_cls.return_value.run.side_effect = run_side_effect
        n = orch.poll_intake()

    assert_that(n, equal_to(1))


@pytest.mark.integration
def test_live_poll_dry_run():
    """Integration: builds a live workspace orchestrator in dry-run and polls one tick."""
    import os
    from agents.projects.orchestrator.local import from_env

    os.environ.setdefault("KANBAN_DRY_RUN", "1")
    orch = from_env()
    orch._ensure_board_orchestrators(orch.discover_boards())
    n = orch.poll_once()
    assert_that(isinstance(n, int), equal_to(True))
