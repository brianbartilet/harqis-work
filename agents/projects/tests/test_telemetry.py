"""
Tests for ES telemetry emitter.

The harqis-core ES library is not actually exercised — `_resolve_es_post` is
patched to return either None (disabled) or a mock that records calls.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from hamcrest import assert_that, contains_string, equal_to

from agents.projects.integrations import telemetry


@pytest.fixture(autouse=True)
def reset_telemetry_module_state():
    """The lazy-import probe caches its result on the module; reset it before
    every test so each test starts from a clean slate."""
    telemetry._es_post = None
    telemetry._es_available = None
    yield
    telemetry._es_post = None
    telemetry._es_available = None


# ── No-op when ES not available ──────────────────────────────────────────────

@pytest.mark.smoke
def test_emit_is_noop_when_library_missing():
    """When the harqis-core import fails, every emit_* must silently no-op."""
    with patch.object(telemetry, "_resolve_es_post", return_value=None):
        # All of these would raise if they tried to call post().
        telemetry.emit_card_claimed(board_id="b", card_id="c", profile_id="p")
        telemetry.emit_agent_started(board_id="b", card_id="c", profile_id="p", model_id="m")
        telemetry.emit_agent_finished(board_id="b", card_id="c", profile_id="p",
                                       destination="In Review", duration_seconds=1.0)
        telemetry.emit_agent_failed(board_id="b", card_id="c", profile_id="p",
                                     kind="api_error", detail="oops")
        telemetry.emit_card_blocked(board_id="b", card_id="c", profile_id="p", reason="x")
        telemetry.emit_card_paused(board_id="b", card_id="c", profile_id="p", stateful=True)


@pytest.mark.smoke
def test_is_enabled_false_when_library_missing():
    with patch.object(telemetry, "_resolve_es_post", return_value=None):
        assert_that(telemetry.is_enabled(), equal_to(False))


# ── Doc shape when ES is configured ──────────────────────────────────────────

@pytest.mark.smoke
def test_emit_card_claimed_sends_expected_payload():
    fake_post = MagicMock()
    with patch.object(telemetry, "_resolve_es_post", return_value=fake_post):
        telemetry.emit_card_claimed(board_id="b1", card_id="card_a", profile_id="agent:code")

    fake_post.assert_called_once()
    kwargs = fake_post.call_args.kwargs
    payload = kwargs["json_dump"]
    assert_that(payload["event"], equal_to("card_claimed"))
    assert_that(payload["board_id"], equal_to("b1"))
    assert_that(payload["card_id"], equal_to("card_a"))
    assert_that(payload["profile_id"], equal_to("agent:code"))
    # Common fields appear automatically.
    assert_that("ts" in payload, equal_to(True))
    assert_that("host" in payload, equal_to(True))
    assert_that("host_os" in payload, equal_to(True))
    # Indexed under the configured index.
    assert_that(kwargs["index_name"], equal_to(telemetry._index_name()))
    # Location key combines board + card so a card's lifecycle docs cluster.
    assert_that(kwargs["location_key"], equal_to("b1/card_a"))


@pytest.mark.smoke
def test_emit_agent_finished_includes_destination_and_duration():
    fake_post = MagicMock()
    with patch.object(telemetry, "_resolve_es_post", return_value=fake_post):
        telemetry.emit_agent_finished(
            board_id="b", card_id="c", profile_id="agent:code",
            destination="In Review", duration_seconds=42.5,
        )
    payload = fake_post.call_args.kwargs["json_dump"]
    assert_that(payload["destination"], equal_to("In Review"))
    assert_that(payload["duration_seconds"], equal_to(42.5))


@pytest.mark.smoke
def test_emit_agent_failed_caps_detail_to_500_chars():
    """Long stack traces must be capped so individual ES docs don't bloat."""
    fake_post = MagicMock()
    with patch.object(telemetry, "_resolve_es_post", return_value=fake_post):
        telemetry.emit_agent_failed(
            board_id="b", card_id="c", profile_id="p",
            kind="api_error", detail="x" * 5000,
        )
    payload = fake_post.call_args.kwargs["json_dump"]
    assert_that(len(payload["detail"]), equal_to(500))
    assert_that(payload["kind"], equal_to("api_error"))


@pytest.mark.smoke
def test_emit_swallows_post_exceptions():
    """A flaky ES must NEVER take down a card — emit_* logs and returns."""
    fake_post = MagicMock()
    fake_post.side_effect = RuntimeError("ES on fire")
    with patch.object(telemetry, "_resolve_es_post", return_value=fake_post):
        # Would raise if exceptions weren't caught.
        telemetry.emit_card_claimed(board_id="b", card_id="c", profile_id="p")


@pytest.mark.smoke
def test_telemetry_index_overridable_by_env(monkeypatch):
    monkeypatch.setenv("KANBAN_TELEMETRY_INDEX", "my-custom-index")
    fake_post = MagicMock()
    with patch.object(telemetry, "_resolve_es_post", return_value=fake_post):
        telemetry.emit_card_claimed(board_id="b", card_id="c", profile_id="p")
    assert_that(fake_post.call_args.kwargs["index_name"], equal_to("my-custom-index"))


# ── Resolve probe behaviour ──────────────────────────────────────────────────

@pytest.mark.smoke
def test_resolve_es_post_caches_result():
    """The first import attempt is cached so we don't pay the import cost on
    every emit. Subsequent calls return the cached value without re-importing."""
    # Simulate "library available" by stuffing a sentinel into the cache.
    sentinel = object()
    telemetry._es_post = sentinel
    telemetry._es_available = True
    assert_that(telemetry._resolve_es_post() is sentinel, equal_to(True))


@pytest.mark.smoke
def test_resolve_es_post_caches_unavailable():
    telemetry._es_post = None
    telemetry._es_available = False
    assert_that(telemetry._resolve_es_post() is None, equal_to(True))
