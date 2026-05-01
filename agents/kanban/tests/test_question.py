"""
Tests for the agent ↔ human question/answer protocol.

Covers:
  - State serialisation / deserialisation round-trip
  - Resume signal detection (has-question + has-human-reply)
  - is_agent_authored heuristic
  - AskHumanTool: posts comment, adds label, raises pause exception
  - BaseKanbanAgent: pause propagates out of run() cleanly
  - BaseKanbanAgent: stateful resume picks up prior_messages
  - LocalOrchestrator.poll_resumes wiring (offline, mocked provider)
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from agents.kanban.agent.base import BaseKanbanAgent
from agents.kanban.agent.question import (
    AgentPausedForQuestion,
    QUESTION_LABEL,
    QUESTION_MARKER,
    REMEMBER_LABEL,
    build_recap_prompt,
    extract_state,
    find_resume_signal,
    is_agent_authored,
    serialize_state,
)
from agents.kanban.agent.tools.kanban_tools import AskHumanTool


# ── State serialise/deserialise ───────────────────────────────────────────────

def test_state_serialize_round_trip():
    messages = [
        {"role": "user", "content": "do the thing"},
        {"role": "assistant", "content": [{"type": "text", "text": "ok"}]},
    ]
    body = serialize_state(messages, iteration=3, profile_id="agent:default", model_id="claude-sonnet-4-6")
    assert body.startswith("<!-- AGENT_STATE_V1:")
    assert body.endswith("-->")
    payload = extract_state([body])
    assert payload is not None
    assert payload["v"] == 1
    assert payload["iteration"] == 3
    assert payload["profile_id"] == "agent:default"
    assert payload["model_id"] == "claude-sonnet-4-6"
    assert payload["messages"] == messages


def test_state_extract_picks_latest():
    older = serialize_state([{"role": "user", "content": "old"}], 1, "agent:x", "m")
    newer = serialize_state([{"role": "user", "content": "new"}], 2, "agent:x", "m")
    payload = extract_state(["unrelated comment", older, "another comment", newer])
    assert payload is not None
    assert payload["iteration"] == 2
    assert payload["messages"][0]["content"] == "new"


def test_state_extract_returns_none_when_no_marker():
    payload = extract_state(["regular comment", f"{QUESTION_MARKER} should I?"])
    assert payload is None


def test_state_extract_skips_corrupt_block():
    corrupt = "<!-- AGENT_STATE_V1:not-base64-!@#$ -->"
    valid = serialize_state([{"role": "user", "content": "ok"}], 5, "p", "m")
    payload = extract_state([corrupt, valid])
    assert payload is not None
    assert payload["iteration"] == 5


# ── is_agent_authored heuristic ───────────────────────────────────────────────

@pytest.mark.parametrize("comment", [
    f"{QUESTION_MARKER} should I do X?",
    "## Result\n\nDone.",
    "## Agent Error\n\nstack",
    "## Agent: Blocked\n\ndeps",
    "claimed-by: Claude · Default",
    "<!-- AGENT_STATE_V1:abc -->",
])
def test_is_agent_authored_recognises_agent_prefixes(comment):
    assert is_agent_authored(comment) is True


@pytest.mark.parametrize("comment", [
    "yes go ahead",
    "Use option 2 please.",
    "",
    "I'd prefer not to do that — try the alternative.",
])
def test_is_agent_authored_rejects_human_text(comment):
    assert is_agent_authored(comment) is False


# ── find_resume_signal ────────────────────────────────────────────────────────

def test_resume_signal_none_when_no_question():
    assert find_resume_signal(["nothing here", "## Result\n\ndone"]) is None


def test_resume_signal_none_when_question_but_no_reply():
    comments = [
        "claimed-by: Claude · Default",
        f"{QUESTION_MARKER} approve draft?",
    ]
    assert find_resume_signal(comments) is None


def test_resume_signal_detects_human_reply_after_question():
    comments = [
        "claimed-by: Claude · Default",
        f"{QUESTION_MARKER} approve draft?",
        "yes please go ahead",
    ]
    signal = find_resume_signal(comments)
    assert signal is not None
    idx, replies = signal
    assert idx == 1
    assert replies == ["yes please go ahead"]


def test_resume_signal_uses_most_recent_question_only():
    comments = [
        f"{QUESTION_MARKER} v1?",
        "first reply",
        "## Result\n\nintermediate",
        f"{QUESTION_MARKER} v2?",
        "second reply",
    ]
    signal = find_resume_signal(comments)
    assert signal is not None
    idx, replies = signal
    assert idx == 3                 # most recent question
    assert replies == ["second reply"]


def test_resume_signal_filters_agent_comments_after_question():
    comments = [
        f"{QUESTION_MARKER} ready?",
        "## Result\n\nintermediate",   # agent — should NOT count as a reply
        "ok do it",                     # human reply
    ]
    signal = find_resume_signal(comments)
    assert signal is not None
    idx, replies = signal
    assert replies == ["ok do it"]


# ── build_recap_prompt ────────────────────────────────────────────────────────

def test_recap_prompt_includes_question_and_reply():
    out = build_recap_prompt(
        f"{QUESTION_MARKER} option A or B?",
        ["B please"],
    )
    assert "option A or B?" in out
    assert "B please" in out
    assert "Resuming after a human reply" in out


def test_recap_prompt_handles_multi_part_reply():
    out = build_recap_prompt(
        f"{QUESTION_MARKER} which?",
        ["actually wait", "use C"],
    )
    assert "actually wait" in out
    assert "use C" in out


# ── AskHumanTool ──────────────────────────────────────────────────────────────

def test_ask_human_posts_comment_adds_label_and_raises():
    provider = MagicMock()
    tool = AskHumanTool(provider, card_id="card1", card_labels=["agent:default"])

    with pytest.raises(AgentPausedForQuestion) as info:
        tool.run(question="proceed?")

    assert info.value.stateful is False
    provider.add_comment.assert_called_once()
    body_arg = provider.add_comment.call_args[0][1]
    assert body_arg.startswith(QUESTION_MARKER)
    assert "proceed?" in body_arg
    provider.add_label.assert_called_once_with("card1", QUESTION_LABEL)


def test_ask_human_renders_options_as_bullets():
    provider = MagicMock()
    tool = AskHumanTool(provider, card_id="c", card_labels=[])
    with pytest.raises(AgentPausedForQuestion):
        tool.run(question="which?", options=["A", "B", "C"])
    body = provider.add_comment.call_args[0][1]
    assert "- A" in body and "- B" in body and "- C" in body


def test_ask_human_calls_save_state_when_remember_label_present():
    provider = MagicMock()
    save = MagicMock()
    tool = AskHumanTool(
        provider, card_id="c",
        card_labels=[REMEMBER_LABEL, "agent:default"],
        save_state_fn=save,
    )
    with pytest.raises(AgentPausedForQuestion) as info:
        tool.run(question="?")
    save.assert_called_once()
    assert info.value.stateful is True


def test_ask_human_skips_save_state_when_label_absent():
    provider = MagicMock()
    save = MagicMock()
    tool = AskHumanTool(provider, card_id="c", card_labels=["agent:default"], save_state_fn=save)
    with pytest.raises(AgentPausedForQuestion):
        tool.run(question="?")
    save.assert_not_called()


def test_ask_human_label_failure_is_non_fatal():
    provider = MagicMock()
    provider.add_label.side_effect = RuntimeError("trello 5xx")
    tool = AskHumanTool(provider, card_id="c", card_labels=[])
    with pytest.raises(AgentPausedForQuestion):
        tool.run(question="?")
    # Comment was still posted; pause exception still raised.
    provider.add_comment.assert_called_once()


# ── BaseKanbanAgent — pause propagation ───────────────────────────────────────

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


def _make_text_response(text: str):
    block = MagicMock()
    block.type = "text"
    block.text = text
    response = MagicMock()
    response.content = [block]
    response.stop_reason = "end_turn"
    return response


def test_agent_run_propagates_pause_exception(open_profile, sample_card):
    """When the agent calls ask_human, AgentPausedForQuestion bubbles out of run()."""
    provider = MagicMock()
    tool_response = _make_tool_response("ask_human", {"question": "go ahead?"})

    with patch("anthropic.Anthropic") as mock_anthropic:
        client = MagicMock()
        mock_anthropic.return_value = client
        client.messages.create.return_value = tool_response

        agent = BaseKanbanAgent(
            profile=open_profile,
            card=sample_card,
            provider=provider,
            api_key="test",
        )
        with pytest.raises(AgentPausedForQuestion) as info:
            agent.run()

    assert info.value.question == "go ahead?"
    # The tool ran — comment was posted and label was added before pausing.
    provider.add_comment.assert_called_once()
    provider.add_label.assert_called_once()


def test_agent_run_starts_from_prior_messages_when_provided(open_profile, sample_card):
    """Stateful resume: prior_messages is used in place of fresh context."""
    provider = MagicMock()
    final = _make_text_response("resumed and done")
    prior = [
        {"role": "user", "content": "earlier task"},
        {"role": "assistant", "content": [{"type": "text", "text": "asked you something"}]},
    ]

    with patch("anthropic.Anthropic") as mock_anthropic:
        client = MagicMock()
        mock_anthropic.return_value = client
        client.messages.create.return_value = final

        agent = BaseKanbanAgent(
            profile=open_profile,
            card=sample_card,
            provider=provider,
            api_key="test",
            prior_messages=prior,
            prior_iteration=4,
            resume_user_message="here is my reply",
        )
        result = agent.run()

    assert result == "resumed and done"
    # MagicMock's call_args holds a reference to the messages list, so the
    # final appended assistant turn shows up too. We care that the prior
    # messages and the resume user message were in the right slots.
    sent = client.messages.create.call_args.kwargs["messages"]
    assert sent[0] == prior[0]
    assert sent[1] == prior[1]
    assert sent[2] == {"role": "user", "content": "here is my reply"}


# ── Orchestrator resume wiring ────────────────────────────────────────────────

def _make_orchestrator(provider: MagicMock, profile_id: str = "agent:default"):
    """Return a LocalOrchestrator wired to the given mock provider, with a
    minimal registry that always returns a permissive profile."""
    from agents.kanban.orchestrator.local import LocalOrchestrator

    profile = MagicMock()
    profile.id = profile_id
    profile.name = "Test"
    profile.lifecycle.detect_dependencies = False
    profile.lifecycle.block_on_missing_secrets = False
    profile.provider_credentials.is_set.return_value = False
    profile.tools.allowed = []

    registry = MagicMock()
    registry.resolve_for_card.return_value = profile
    registry.__iter__ = lambda self: iter([])
    registry.__len__ = lambda self: 0

    orch = LocalOrchestrator(
        provider=provider,
        registry=registry,
        api_key="test",
        board_id="board",
        poll_interval=1,
    )
    # Bypass routing filter for tests
    orch.profile_filter = None
    orch.hw_labels = set()
    return orch, profile


def test_poll_resumes_skips_cards_without_question_label(sample_card):
    provider = MagicMock()
    sample_card.labels = ["agent:default"]   # no agent:question
    sample_card.column = "In Progress"
    provider.get_cards.return_value = [sample_card]

    orch, _ = _make_orchestrator(provider)
    n = orch.poll_resumes()
    assert n == 0
    # Did NOT fetch comments because the label wasn't present
    provider.get_comments.assert_not_called()


def test_poll_resumes_skips_when_no_human_reply_yet(sample_card):
    provider = MagicMock()
    sample_card.labels = ["agent:default", QUESTION_LABEL]
    provider.get_cards.return_value = [sample_card]
    provider.get_comments.return_value = [
        "claimed-by: Claude · Default",
        f"{QUESTION_MARKER} approve?",
    ]

    orch, _ = _make_orchestrator(provider)
    n = orch.poll_resumes()
    assert n == 0
    # Did not attempt to remove the label — no resume happened
    provider.remove_label.assert_not_called()


def test_poll_resumes_dispatches_when_human_replied(sample_card):
    provider = MagicMock()
    sample_card.labels = ["agent:default", QUESTION_LABEL]
    provider.get_cards.return_value = [sample_card]
    provider.get_comments.return_value = [
        "claimed-by: Claude · Default",
        f"{QUESTION_MARKER} approve?",
        "yes go ahead",
    ]

    orch, _profile = _make_orchestrator(provider)
    # Stub resume_card so we don't actually invoke the agent
    orch.resume_card = MagicMock(return_value=True)
    n = orch.poll_resumes()
    assert n == 1
    orch.resume_card.assert_called_once()
    args = orch.resume_card.call_args
    # Verify the signal was extracted correctly
    assert args.args[3][1] == ["yes go ahead"]
