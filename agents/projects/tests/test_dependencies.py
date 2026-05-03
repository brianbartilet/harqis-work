"""
Tests for agents/kanban/dependencies/detector.py

All tests run offline — no API calls, no env vars required.
"""

from __future__ import annotations

import os
from unittest.mock import patch

import pytest
from hamcrest import assert_that, equal_to, has_length, is_, not_

from agents.projects.dependencies.detector import (
    Dependency,
    DependencyDetector,
    DependencyType,
    DetectionResult,
)
from agents.projects.trello.models import KanbanCard


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture()
def detector():
    return DependencyDetector()


def _card(title: str = "Task", description: str = "", custom_fields: dict | None = None) -> KanbanCard:
    return KanbanCard(
        id="card1",
        title=title,
        description=description,
        labels=["agent:full"],
        assignees=[],
        column="Backlog",
        url="https://trello.com/c/card1",
        custom_fields=custom_fields or {},
    )


# ── DetectionResult ───────────────────────────────────────────────────────────

@pytest.mark.smoke
def test_detection_result_has_blocking_false_when_empty():
    result = DetectionResult()
    assert_that(result.has_blocking, equal_to(False))


@pytest.mark.smoke
def test_detection_result_has_blocking_true_when_blocking_dep():
    result = DetectionResult(
        blocking=[Dependency(
            type=DependencyType.SECRET,
            name="MY_KEY",
            blocking=True,
            description="Missing key",
        )]
    )
    assert_that(result.has_blocking, equal_to(True))


@pytest.mark.smoke
def test_detection_result_blocker_summary_lists_deps():
    result = DetectionResult(
        blocking=[
            Dependency(
                type=DependencyType.SECRET,
                name="API_KEY",
                blocking=True,
                description="Key not set",
                hint="Add it to agents.env",
            )
        ]
    )
    summary = result.blocker_summary()
    assert_that(summary, not_(equal_to("")))
    assert "API_KEY" in summary
    assert "Add it to agents.env" in summary


@pytest.mark.smoke
def test_detection_result_blocker_summary_empty_when_no_blocking():
    result = DetectionResult()
    assert_that(result.blocker_summary(), equal_to(""))


# ── Explicit required_secrets ─────────────────────────────────────────────────

@pytest.mark.smoke
def test_detect_no_blocking_when_no_custom_field(detector):
    card = _card()
    with patch.dict(os.environ, {}, clear=False):
        result = detector.detect(card)
    assert_that(result.has_blocking, equal_to(False))


@pytest.mark.smoke
def test_detect_blocking_when_required_secret_missing(detector):
    card = _card(custom_fields={"required_secrets": "MY_MISSING_KEY"})
    env_without_key = {k: v for k, v in os.environ.items() if k != "MY_MISSING_KEY"}
    with patch.dict(os.environ, env_without_key, clear=True):
        result = detector.detect(card)
    assert_that(result.has_blocking, equal_to(True))
    assert_that(result.blocking[0].name, equal_to("MY_MISSING_KEY"))
    assert_that(result.blocking[0].type, equal_to(DependencyType.SECRET))


@pytest.mark.smoke
def test_detect_no_blocking_when_required_secret_present(detector):
    card = _card(custom_fields={"required_secrets": "MY_PRESENT_KEY"})
    with patch.dict(os.environ, {"MY_PRESENT_KEY": "secret-value"}, clear=False):
        result = detector.detect(card)
    assert_that(result.has_blocking, equal_to(False))


@pytest.mark.smoke
def test_detect_multiple_secrets_some_missing(detector):
    card = _card(custom_fields={"required_secrets": "KEY_A,KEY_B,KEY_C"})
    with patch.dict(os.environ, {"KEY_A": "present"}, clear=False):
        # Remove KEY_B and KEY_C
        env = {k: v for k, v in os.environ.items() if k not in ("KEY_B", "KEY_C")}
        with patch.dict(os.environ, env, clear=True):
            result = detector.detect(card)
    # KEY_B and KEY_C are missing; result should have blocking deps
    missing = {d.name for d in result.blocking}
    assert "KEY_B" in missing or "KEY_C" in missing


# ── Service reference scanning ────────────────────────────────────────────────

@pytest.mark.smoke
def test_detect_oanda_reference_when_key_missing(detector):
    card = _card(description="Fetch OANDA candles for EUR/USD")
    env = {k: v for k, v in os.environ.items() if "OANDA" not in k}
    with patch.dict(os.environ, env, clear=True):
        result = detector.detect(card)
    oanda_deps = [d for d in result.blocking if "OANDA" in d.name]
    assert_that(len(oanda_deps) > 0, equal_to(True))


@pytest.mark.smoke
def test_detect_no_blocking_when_service_key_present(detector):
    card = _card(description="Post a message to DISCORD")
    with patch.dict(os.environ, {"DISCORD_BOT_TOKEN": "tok123"}, clear=False):
        result = detector.detect(card)
    discord_blocks = [d for d in result.blocking if "DISCORD" in d.name]
    assert_that(len(discord_blocks), equal_to(0))


@pytest.mark.smoke
def test_detect_no_service_refs_in_plain_card(detector):
    card = _card(description="Read and summarize the README file")
    result = detector.detect(card)
    assert_that(result.has_blocking, equal_to(False))


# ── Soft dependency detection ─────────────────────────────────────────────────

@pytest.mark.smoke
def test_detect_new_workflow_soft_dep(detector):
    card = _card(description="Create a new workflow to sync Trello data")
    result = detector.detect(card)
    wf_deps = [d for d in result.soft if d.type == DependencyType.NEW_WORKFLOW]
    assert_that(len(wf_deps) > 0, equal_to(True))
    assert_that(wf_deps[0].blocking, equal_to(False))


@pytest.mark.smoke
def test_detect_new_app_soft_dep(detector):
    card = _card(description="Scaffold a new MCP app for the Spotify API")
    result = detector.detect(card)
    app_deps = [d for d in result.soft if d.type == DependencyType.NEW_APP]
    assert_that(len(app_deps) > 0, equal_to(True))
    assert_that(app_deps[0].blocking, equal_to(False))


@pytest.mark.smoke
def test_detect_no_soft_deps_in_plain_card(detector):
    card = _card(description="Fix the login page button alignment")
    result = detector.detect(card)
    assert_that(result.soft, has_length(0))


# ── Deduplication ─────────────────────────────────────────────────────────────

@pytest.mark.smoke
def test_detect_deduplicates_blocking_deps(detector):
    # Both explicit required_secrets and service scan might flag DISCORD_BOT_TOKEN
    card = _card(
        description="Send a DISCORD notification",
        custom_fields={"required_secrets": "DISCORD_BOT_TOKEN"},
    )
    env = {k: v for k, v in os.environ.items() if "DISCORD" not in k}
    with patch.dict(os.environ, env, clear=True):
        result = detector.detect(card)
    discord_deps = [d for d in result.blocking if "DISCORD_BOT_TOKEN" == d.name]
    assert_that(len(discord_deps), equal_to(1))
