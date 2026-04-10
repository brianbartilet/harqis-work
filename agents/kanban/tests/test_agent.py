"""
Tests for BaseKanbanAgent — Claude tool-use loop.
All Anthropic API calls are mocked.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch, call

import pytest
from hamcrest import assert_that, equal_to, contains_string, instance_of

from agents.kanban.agent.base import BaseKanbanAgent
from agents.kanban.agent.context import AgentContext, build_card_context


# ── Helpers ───────────────────────────────────────────────────────────────────

def _make_text_response(text: str, stop_reason: str = "end_turn"):
    block = MagicMock()
    block.type = "text"
    block.text = text
    response = MagicMock()
    response.content = [block]
    response.stop_reason = stop_reason
    return response


def _make_tool_response(tool_name: str, tool_input: dict, tool_id: str = "tu_1"):
    block = MagicMock()
    block.type = "tool_use"
    block.name = tool_name
    block.input = tool_input
    block.id = tool_id
    response = MagicMock()
    response.content = [block]
    response.stop_reason = "tool_use"
    return response


# ── Tests ─────────────────────────────────────────────────────────────────────

@pytest.mark.smoke
def test_agent_returns_text_on_end_turn(open_profile, sample_card):
    provider = MagicMock()

    with patch("anthropic.Anthropic") as mock_anthropic:
        mock_client = MagicMock()
        mock_anthropic.return_value = mock_client
        mock_client.messages.create.return_value = _make_text_response("Task complete!")

        agent = BaseKanbanAgent(
            profile=open_profile,
            card=sample_card,
            provider=provider,
            api_key="test_key",
        )
        result = agent.run()

    assert_that(result, equal_to("Task complete!"))


@pytest.mark.smoke
def test_agent_calls_tool_then_finishes(open_profile, sample_card):
    provider = MagicMock()

    tool_response = _make_tool_response("read_file", {"path": "/tmp/test.txt"})
    final_response = _make_text_response("Done reading the file.")

    with patch("anthropic.Anthropic") as mock_anthropic:
        mock_client = MagicMock()
        mock_anthropic.return_value = mock_client
        mock_client.messages.create.side_effect = [tool_response, final_response]

        with patch("agents.kanban.agent.tools.filesystem.ReadFileTool.run") as mock_read:
            mock_read.return_value = "file contents here"
            agent = BaseKanbanAgent(
                profile=open_profile,
                card=sample_card,
                provider=provider,
                api_key="test_key",
            )
            result = agent.run()

    assert_that(result, equal_to("Done reading the file."))
    # Claude was called twice: tool call + final
    assert_that(mock_client.messages.create.call_count, equal_to(2))


@pytest.mark.smoke
def test_agent_handles_permission_denied_gracefully(restricted_profile, sample_card):
    provider = MagicMock()

    # Agent tries to call bash (denied)
    tool_response = _make_tool_response("bash", {"command": "ls"})
    final_response = _make_text_response("I was unable to run the bash command.")

    with patch("anthropic.Anthropic") as mock_anthropic:
        mock_client = MagicMock()
        mock_anthropic.return_value = mock_client
        mock_client.messages.create.side_effect = [tool_response, final_response]

        agent = BaseKanbanAgent(
            profile=restricted_profile,
            card=sample_card,
            provider=provider,
            api_key="test_key",
        )
        result = agent.run()

    # Should complete without raising — permission denial is reported as a tool_result error
    assert_that(result, equal_to("I was unable to run the bash command."))

    # Inspect messages passed to the second Claude call.
    # Note: the list is mutated after the call (assistant message appended),
    # so we search all messages for the tool_result error entry.
    second_call_messages = mock_client.messages.create.call_args_list[1].kwargs["messages"]
    tool_results = [
        item
        for msg in second_call_messages
        if isinstance(msg, dict) and msg.get("role") == "user"
        for item in (msg.get("content") or [])
        if isinstance(item, dict) and item.get("type") == "tool_result"
    ]
    assert_that(len(tool_results) > 0, equal_to(True))
    assert_that(tool_results[0].get("is_error"), equal_to(True))
    assert_that(tool_results[0]["content"], contains_string("PERMISSION DENIED"))


@pytest.mark.smoke
def test_agent_system_prompt_includes_profile_name(open_profile, sample_card):
    provider = MagicMock()

    with patch("anthropic.Anthropic") as mock_anthropic:
        mock_client = MagicMock()
        mock_anthropic.return_value = mock_client
        mock_client.messages.create.return_value = _make_text_response("ok")

        agent = BaseKanbanAgent(
            profile=open_profile,
            card=sample_card,
            provider=provider,
            api_key="test_key",
        )
        agent.run()

    call_kwargs = mock_client.messages.create.call_args.kwargs
    assert_that(call_kwargs["system"], contains_string(open_profile.name))


@pytest.mark.smoke
def test_agent_tool_definitions_respect_allowed_list(restricted_profile, sample_card):
    provider = MagicMock()
    with patch("anthropic.Anthropic"):
        agent = BaseKanbanAgent(
            profile=restricted_profile,
            card=sample_card,
            provider=provider,
            api_key="test_key",
        )
        definitions = agent.registry.definitions()

    tool_names = [d["name"] for d in definitions]
    # Only allowed tools should appear
    assert_that("bash" in tool_names, equal_to(False))
    assert_that("write_file" in tool_names, equal_to(False))
    assert_that("read_file" in tool_names, equal_to(True))
    assert_that("post_comment" in tool_names, equal_to(True))


@pytest.mark.smoke
def test_agent_stops_at_max_iterations(open_profile, sample_card):
    provider = MagicMock()
    # Always return tool_use — no end_turn
    always_tool = _make_tool_response("post_comment", {"text": "progress"})

    with patch("anthropic.Anthropic") as mock_anthropic:
        mock_client = MagicMock()
        mock_anthropic.return_value = mock_client
        mock_client.messages.create.return_value = always_tool

        with patch("agents.kanban.agent.tools.kanban_tools.TrelloCommentTool.run") as mock_comment:
            mock_comment.return_value = "ok"
            agent = BaseKanbanAgent(
                profile=open_profile,
                card=sample_card,
                provider=provider,
                api_key="test_key",
            )
            result = agent.run()

    assert_that(result, contains_string("ERROR"))
    assert_that(mock_client.messages.create.call_count, equal_to(30))
