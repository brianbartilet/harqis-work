"""Tests for persona signature rendering (Mode B) and per-profile provider
selection (Mode A)."""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from hamcrest import assert_that, equal_to, contains_string

from agents.kanban.agent.persona import format_signature_block, has_persona, sign_comment
from agents.kanban.orchestrator.local import LocalOrchestrator
from agents.kanban.profiles.registry import ProfileRegistry
from agents.kanban.profiles.schema import (
    AgentProfile,
    PersonaConfig,
    ProviderCredentialsConfig,
)


def _profile_with_persona(**persona_kwargs) -> AgentProfile:
    return AgentProfile(
        id="agent:test",
        name="Test Agent",
        persona=PersonaConfig(**persona_kwargs),
    )


# ── Mode B: persona signing ───────────────────────────────────────────────────

@pytest.mark.smoke
def test_has_persona_false_when_all_fields_empty():
    assert_that(has_persona(AgentProfile(id="x", name="y")), equal_to(False))


@pytest.mark.smoke
def test_has_persona_true_with_just_display_name():
    assert_that(has_persona(_profile_with_persona(display_name="Bob")), equal_to(True))


@pytest.mark.smoke
def test_signature_block_renders_name_role_and_email():
    profile = _profile_with_persona(
        display_name="Claude · Code",
        role="Code-writing agent",
        email="claude-code@harqis.local",
        signature="Reply on the card to redirect.",
    )
    block = format_signature_block(profile)
    assert_that(block, contains_string("Claude · Code"))
    assert_that(block, contains_string("Code-writing agent"))
    assert_that(block, contains_string("claude-code@harqis.local"))
    assert_that(block, contains_string("Reply on the card to redirect."))


@pytest.mark.smoke
def test_signature_block_includes_avatar_when_set():
    profile = _profile_with_persona(
        display_name="Bot",
        avatar_url="https://example.com/a.png",
    )
    block = format_signature_block(profile)
    assert_that(block, contains_string("![Bot](https://example.com/a.png)"))


@pytest.mark.smoke
def test_sign_comment_noop_when_persona_empty():
    profile = AgentProfile(id="x", name="y")
    assert_that(sign_comment(profile, "hello"), equal_to("hello"))


@pytest.mark.smoke
def test_sign_comment_prefixes_block():
    profile = _profile_with_persona(display_name="Bot", role="Tester")
    out = sign_comment(profile, "## Result\n\nDone.")
    assert_that(out.startswith("> 👤"), equal_to(True))
    assert_that(out, contains_string("## Result"))


# ── Mode A: per-profile provider routing ──────────────────────────────────────

@pytest.fixture()
def global_provider():
    return MagicMock(name="global_provider")


@pytest.fixture()
def orchestrator(global_provider):
    registry = MagicMock(spec=ProfileRegistry)
    return LocalOrchestrator(
        provider=global_provider,
        registry=registry,
        api_key="apk",
        board_id="board",
        provider_config={"provider": "trello", "api_key": "GK", "token": "GT"},
    )


@pytest.mark.smoke
def test_provider_for_profile_uses_global_when_no_creds(orchestrator, global_provider):
    profile = AgentProfile(id="agent:plain", name="Plain")
    assert_that(orchestrator.provider_for_profile(profile) is global_provider, equal_to(True))


@pytest.mark.smoke
def test_provider_for_profile_falls_back_to_global_when_env_unset(orchestrator, global_provider):
    profile = AgentProfile(
        id="agent:code",
        name="Code",
        provider_credentials=ProviderCredentialsConfig(
            trello_api_key_env="TRELLO_AGENT_API_KEY__CODE",
            trello_api_token_env="TRELLO_AGENT_API_TOKEN__CODE",
        ),
    )
    # Both env vars unset → fall back to global (Mode B path).
    with patch.dict("os.environ", {}, clear=False) as _:
        # Make sure the agent-specific vars are absent.
        import os
        os.environ.pop("TRELLO_AGENT_API_KEY__CODE", None)
        os.environ.pop("TRELLO_AGENT_API_TOKEN__CODE", None)
        result = orchestrator.provider_for_profile(profile)
    assert_that(result is global_provider, equal_to(True))


@pytest.mark.smoke
def test_provider_for_profile_builds_per_profile_when_env_set(orchestrator, global_provider):
    profile = AgentProfile(
        id="agent:code",
        name="Code",
        provider_credentials=ProviderCredentialsConfig(
            trello_api_key_env="TRELLO_AGENT_API_KEY__CODE",
            trello_api_token_env="TRELLO_AGENT_API_TOKEN__CODE",
        ),
    )
    fake_per_profile = MagicMock(name="per_profile_provider")
    with patch.dict(
        "os.environ",
        {
            "TRELLO_AGENT_API_KEY__CODE": "AGENT_KEY",
            "TRELLO_AGENT_API_TOKEN__CODE": "AGENT_TOKEN",
        },
        clear=False,
    ):
        with patch(
            "agents.kanban.orchestrator.local.create_provider",
            return_value=fake_per_profile,
        ) as mock_create:
            result = orchestrator.provider_for_profile(profile)
            # Cached on second call — create_provider not invoked again.
            again = orchestrator.provider_for_profile(profile)

    assert_that(result is fake_per_profile, equal_to(True))
    assert_that(again is fake_per_profile, equal_to(True))
    assert_that(mock_create.call_count, equal_to(1))
    # Verify the per-profile config got the agent's creds, not the global ones.
    cfg = mock_create.call_args.args[0]
    assert_that(cfg["api_key"], equal_to("AGENT_KEY"))
    assert_that(cfg["token"], equal_to("AGENT_TOKEN"))


@pytest.mark.smoke
def test_post_comment_signs_in_mode_b(orchestrator, global_provider):
    profile = _profile_with_persona(display_name="Bot", role="Tester")
    orchestrator._post_comment("card_1", "## Body", profile)
    args = global_provider.add_comment.call_args.args
    assert_that(args[0], equal_to("card_1"))
    assert_that(args[1], contains_string("👤"))
    assert_that(args[1], contains_string("## Body"))


@pytest.mark.smoke
def test_post_comment_does_not_sign_in_mode_a(orchestrator, global_provider):
    profile = AgentProfile(
        id="agent:code",
        name="Code",
        persona=PersonaConfig(display_name="Bot", role="Tester"),
        provider_credentials=ProviderCredentialsConfig(
            trello_api_key_env="TRELLO_AGENT_API_KEY__CODE",
            trello_api_token_env="TRELLO_AGENT_API_TOKEN__CODE",
        ),
    )
    fake_per_profile = MagicMock(name="per_profile_provider")
    with patch.dict(
        "os.environ",
        {
            "TRELLO_AGENT_API_KEY__CODE": "AGENT_KEY",
            "TRELLO_AGENT_API_TOKEN__CODE": "AGENT_TOKEN",
        },
        clear=False,
    ):
        with patch(
            "agents.kanban.orchestrator.local.create_provider",
            return_value=fake_per_profile,
        ):
            orchestrator._post_comment("card_1", "## Body", profile)

    # Comment goes to the per-profile provider with no signature prefix.
    fake_per_profile.add_comment.assert_called_once_with("card_1", "## Body")
    global_provider.add_comment.assert_not_called()
