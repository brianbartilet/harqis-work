"""Tests for the agent:default fallback + orchestrator profile/hw routing."""
from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from hamcrest import assert_that, equal_to, is_

from agents.kanban.interface import KanbanCard
from agents.kanban.orchestrator.local import (
    LocalOrchestrator,
    card_hw_required,
    detect_local_hw_labels,
    is_human_card,
)
from agents.kanban.profiles.registry import DEFAULT_PROFILE_ID, ProfileRegistry
from agents.kanban.profiles.schema import AgentProfile


def _card(card_id: str = "c1", labels=None) -> KanbanCard:
    return KanbanCard(
        id=card_id,
        title="t",
        description="d",
        labels=labels or [],
        assignees=[],
        column="Backlog",
        url="https://example/board/c1",
    )


def _profile(pid: str) -> AgentProfile:
    return AgentProfile(id=pid, name=pid)


# ── ProfileRegistry: agent:default fallback ──────────────────────────────────

@pytest.fixture()
def registry_with_default():
    r = ProfileRegistry()
    r.register(_profile("agent:default"))
    r.register(_profile("agent:code"))
    return r


@pytest.fixture()
def registry_no_default():
    r = ProfileRegistry()
    r.register(_profile("agent:code"))
    return r


@pytest.mark.smoke
def test_resolve_returns_specific_profile_when_label_matches(registry_with_default):
    card = _card(labels=["agent:code"])
    result = registry_with_default.resolve_for_card(card)
    assert_that(result.id, equal_to("agent:code"))


@pytest.mark.smoke
def test_resolve_falls_back_to_default_when_no_agent_label(registry_with_default):
    card = _card(labels=["hw:linux", "priority:high"])
    result = registry_with_default.resolve_for_card(card)
    assert_that(result.id, equal_to(DEFAULT_PROFILE_ID))


@pytest.mark.smoke
def test_resolve_falls_back_to_default_when_no_labels_at_all(registry_with_default):
    card = _card(labels=[])
    result = registry_with_default.resolve_for_card(card)
    assert_that(result.id, equal_to(DEFAULT_PROFILE_ID))


@pytest.mark.smoke
def test_resolve_returns_none_for_unknown_agent_label(registry_with_default):
    """A typo like agent:nonexistent must NOT silently route to default —
    surface the typo by returning None so the orchestrator skips the card."""
    card = _card(labels=["agent:nonexistent"])
    result = registry_with_default.resolve_for_card(card)
    assert_that(result, is_(None))


@pytest.mark.smoke
def test_resolve_returns_none_when_no_default_and_no_match(registry_no_default):
    card = _card(labels=[])
    result = registry_no_default.resolve_for_card(card)
    assert_that(result, is_(None))


# ── Hardware label detection ─────────────────────────────────────────────────

@pytest.mark.smoke
def test_detect_local_hw_labels_returns_at_least_one():
    labels = detect_local_hw_labels()
    assert_that(len(labels) >= 1, equal_to(True))
    assert_that(all(l.startswith("hw:") for l in labels), equal_to(True))


@pytest.mark.smoke
def test_card_hw_required_extracts_hw_labels():
    card = _card(labels=["agent:code", "hw:linux", "hw:gpu", "priority:high"])
    required = card_hw_required(card)
    assert_that(required, equal_to({"hw:linux", "hw:gpu"}))


@pytest.mark.smoke
def test_card_hw_required_empty_when_no_hw_labels():
    card = _card(labels=["agent:code", "priority:high"])
    assert_that(card_hw_required(card), equal_to(set()))


# ── Orchestrator routing: _card_is_for_me ────────────────────────────────────

@pytest.fixture()
def orchestrator():
    return LocalOrchestrator(
        provider=MagicMock(),
        registry=MagicMock(spec=ProfileRegistry),
        api_key="apk",
        board_id="board",
        profile_filter="agent:default",
        hw_labels={"hw:linux"},
    )


@pytest.mark.smoke
def test_card_is_for_me_when_profile_and_hw_match(orchestrator):
    card = _card(labels=["agent:default", "hw:linux"])
    eligible, reason = orchestrator._card_is_for_me(card, _profile("agent:default"))
    assert_that(eligible, equal_to(True))
    assert_that(reason, equal_to(""))


@pytest.mark.smoke
def test_card_is_not_for_me_when_profile_mismatch(orchestrator):
    card = _card(labels=["agent:code"])
    eligible, reason = orchestrator._card_is_for_me(card, _profile("agent:code"))
    assert_that(eligible, equal_to(False))
    assert_that("profile mismatch" in reason, equal_to(True))


@pytest.mark.smoke
def test_card_is_not_for_me_when_hw_mismatch(orchestrator):
    card = _card(labels=["agent:default", "hw:windows"])
    eligible, reason = orchestrator._card_is_for_me(card, _profile("agent:default"))
    assert_that(eligible, equal_to(False))
    assert_that("hw mismatch" in reason, equal_to(True))


@pytest.mark.smoke
def test_card_with_no_hw_label_runs_anywhere(orchestrator):
    """Cards with no hw:* label match any orchestrator regardless of OS."""
    card = _card(labels=["agent:default"])
    eligible, _ = orchestrator._card_is_for_me(card, _profile("agent:default"))
    assert_that(eligible, equal_to(True))


@pytest.mark.smoke
def test_no_profile_filter_means_any_profile_accepted():
    """When profile_filter is None (legacy mode), only hw filtering applies."""
    orch = LocalOrchestrator(
        provider=MagicMock(),
        registry=MagicMock(spec=ProfileRegistry),
        api_key="apk",
        board_id="board",
        profile_filter=None,
        hw_labels={"hw:linux"},
    )
    card = _card(labels=["agent:code"])
    eligible, _ = orch._card_is_for_me(card, _profile("agent:code"))
    assert_that(eligible, equal_to(True))


@pytest.mark.smoke
def test_card_with_multi_hw_label_passes_if_one_matches(orchestrator):
    """Card with multiple hw:* labels passes if THIS orchestrator satisfies any one."""
    card = _card(labels=["agent:default", "hw:linux", "hw:windows"])
    eligible, _ = orchestrator._card_is_for_me(card, _profile("agent:default"))
    assert_that(eligible, equal_to(True))


# ── human / manual skip ───────────────────────────────────────────────────────

@pytest.mark.smoke
def test_is_human_card_true_for_human_label():
    assert_that(is_human_card(_card(labels=["human"])), equal_to(True))


@pytest.mark.smoke
def test_is_human_card_true_for_manual_label():
    assert_that(is_human_card(_card(labels=["manual"])), equal_to(True))


@pytest.mark.smoke
def test_is_human_card_case_insensitive():
    assert_that(is_human_card(_card(labels=["Human"])), equal_to(True))
    assert_that(is_human_card(_card(labels=["MANUAL"])), equal_to(True))


@pytest.mark.smoke
def test_is_human_card_false_for_unrelated_labels():
    assert_that(is_human_card(_card(labels=["agent:code", "hw:linux"])), equal_to(False))


@pytest.mark.smoke
def test_is_human_card_false_for_no_labels():
    assert_that(is_human_card(_card(labels=[])), equal_to(False))


@pytest.mark.smoke
def test_is_human_card_does_not_match_substring():
    """`humanitarian` or `manual-mode` should not match — only the bare label does."""
    assert_that(is_human_card(_card(labels=["humanitarian"])), equal_to(False))
    assert_that(is_human_card(_card(labels=["manual-mode"])), equal_to(False))


@pytest.mark.smoke
def test_process_card_returns_none_for_human_card(orchestrator):
    """Even with a perfectly-matching agent label and hw, a human-tagged card is skipped."""
    card = _card(labels=["agent:default", "hw:linux", "human"])
    result = orchestrator.process_card(card)
    assert_that(result, is_(None))
    # Nothing should be moved or commented on a human card.
    orchestrator.provider.move_card.assert_not_called()
    orchestrator.provider.add_comment.assert_not_called()


@pytest.mark.smoke
def test_human_label_trumps_agent_label(orchestrator):
    """If both `human` and `agent:default` are present, the human label wins."""
    card = _card(labels=["human", "agent:default"])
    assert_that(is_human_card(card), equal_to(True))
    result = orchestrator.process_card(card)
    assert_that(result, is_(None))
