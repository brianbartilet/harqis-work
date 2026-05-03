"""Tests for the agent:default fallback + orchestrator profile/os routing."""
from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest
from hamcrest import assert_that, equal_to, is_

from agents.projects.orchestrator.board import BoardOrchestrator
from agents.projects.orchestrator.routing import (
    card_os_required,
    detect_local_os_labels,
    is_human_card,
)
from agents.projects.profiles.registry import DEFAULT_PROFILE_ID, ProfileRegistry
from agents.projects.profiles.schema import AgentProfile
from agents.projects.security.secret_store import SecretStore
from agents.projects.trello.models import KanbanCard


def _card(card_id: str = "c1", labels=None) -> KanbanCard:
    return KanbanCard(
        id=card_id,
        title="t",
        description="d",
        labels=labels or [],
        assignees=[],
        column="Ready",
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
    card = _card(labels=["os:linux", "priority:high"])
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


# ── OS label detection ───────────────────────────────────────────────────────

@pytest.mark.smoke
def test_detect_local_os_labels_returns_at_least_one():
    labels = detect_local_os_labels()
    assert_that(len(labels) >= 1, equal_to(True))
    assert_that(all(l.startswith("os:") for l in labels), equal_to(True))


@pytest.mark.smoke
def test_detect_local_os_labels_includes_os_any():
    """Wildcard label `os:any` is always satisfied so cards labelled os:any
    get picked up on any host without per-OS configuration."""
    assert_that("os:any" in detect_local_os_labels(), equal_to(True))


@pytest.mark.smoke
def test_card_os_required_extracts_os_labels():
    card = _card(labels=["agent:code", "os:linux", "os:gpu", "priority:high"])
    required = card_os_required(card)
    assert_that(required, equal_to({"os:linux", "os:gpu"}))


@pytest.mark.smoke
def test_card_os_required_empty_when_no_os_labels():
    card = _card(labels=["agent:code", "priority:high"])
    assert_that(card_os_required(card), equal_to(set()))


# ── Orchestrator routing: _card_is_for_me ────────────────────────────────────

@pytest.fixture()
def orchestrator():
    return BoardOrchestrator(
        client=MagicMock(),
        registry=MagicMock(spec=ProfileRegistry),
        api_key="apk",
        board_id="board",
        secret_store=SecretStore(),
        audit_log_path=Path("logs/test_audit.jsonl"),
        os_labels={"os:linux"},
        profile_filter="agent:default",
    )


@pytest.mark.smoke
def test_card_is_for_me_when_profile_and_os_match(orchestrator):
    card = _card(labels=["agent:default", "os:linux"])
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
def test_card_is_not_for_me_when_os_mismatch(orchestrator):
    card = _card(labels=["agent:default", "os:windows"])
    eligible, reason = orchestrator._card_is_for_me(card, _profile("agent:default"))
    assert_that(eligible, equal_to(False))
    assert_that("os mismatch" in reason, equal_to(True))


@pytest.mark.smoke
def test_card_with_no_os_label_runs_anywhere(orchestrator):
    """Cards with no os:* label match any orchestrator regardless of host OS."""
    card = _card(labels=["agent:default"])
    eligible, _ = orchestrator._card_is_for_me(card, _profile("agent:default"))
    assert_that(eligible, equal_to(True))


@pytest.mark.smoke
def test_no_profile_filter_means_any_profile_accepted():
    """When profile_filter is None, only os filtering applies."""
    orch = BoardOrchestrator(
        client=MagicMock(),
        registry=MagicMock(spec=ProfileRegistry),
        api_key="apk",
        board_id="board",
        secret_store=SecretStore(),
        audit_log_path=Path("logs/test_audit.jsonl"),
        os_labels={"os:linux"},
        profile_filter=None,
    )
    card = _card(labels=["agent:code"])
    eligible, _ = orch._card_is_for_me(card, _profile("agent:code"))
    assert_that(eligible, equal_to(True))


@pytest.mark.smoke
def test_card_with_multi_os_label_passes_if_one_matches(orchestrator):
    """Card with multiple os:* labels passes if THIS orchestrator satisfies any one."""
    card = _card(labels=["agent:default", "os:linux", "os:windows"])
    eligible, _ = orchestrator._card_is_for_me(card, _profile("agent:default"))
    assert_that(eligible, equal_to(True))


# ── human / manual / input skip ──────────────────────────────────────────────

@pytest.mark.smoke
def test_is_human_card_true_for_human_label():
    assert_that(is_human_card(_card(labels=["human"])), equal_to(True))


@pytest.mark.smoke
def test_is_human_card_true_for_manual_label():
    assert_that(is_human_card(_card(labels=["manual"])), equal_to(True))


@pytest.mark.smoke
def test_is_human_card_true_for_input_label():
    """`input` was added alongside human/manual in the workspace refactor —
    same off-limits behaviour, signals 'needs human input' rather than 'manual task'."""
    assert_that(is_human_card(_card(labels=["input"])), equal_to(True))


@pytest.mark.smoke
def test_is_human_card_case_insensitive():
    assert_that(is_human_card(_card(labels=["Human"])), equal_to(True))
    assert_that(is_human_card(_card(labels=["MANUAL"])), equal_to(True))
    assert_that(is_human_card(_card(labels=["Input"])), equal_to(True))


@pytest.mark.smoke
def test_is_human_card_false_for_unrelated_labels():
    assert_that(is_human_card(_card(labels=["agent:code", "os:linux"])), equal_to(False))


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
    """Even with a perfectly-matching agent label and os, a human-tagged card is skipped."""
    card = _card(labels=["agent:default", "os:linux", "human"])
    result = orchestrator.process_card(card)
    assert_that(result, is_(None))
    orchestrator.client.move_card.assert_not_called()
    orchestrator.client.add_comment.assert_not_called()


@pytest.mark.smoke
def test_human_label_trumps_agent_label(orchestrator):
    """If both `human` and `agent:default` are present, the human label wins."""
    card = _card(labels=["human", "agent:default"])
    assert_that(is_human_card(card), equal_to(True))
    result = orchestrator.process_card(card)
    assert_that(result, is_(None))
