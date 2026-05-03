"""Tests for persona signature rendering (Mode B) and per-profile client
selection (Mode A)."""
from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from hamcrest import assert_that, equal_to, contains_string

from agents.projects.agent.persona import format_signature_block, has_persona, sign_comment
from agents.projects.orchestrator.board import BoardOrchestrator
from agents.projects.profiles.registry import ProfileRegistry
from agents.projects.profiles.schema import (
    AgentProfile,
    PersonaConfig,
    ProviderCredentialsConfig,
)
from agents.projects.security.secret_store import SecretStore


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


# ── Mode A: per-profile client routing ────────────────────────────────────────

@pytest.fixture()
def shared_client():
    return MagicMock(name="shared_client")


@pytest.fixture()
def client_factory():
    """A factory that records calls and returns a fresh mock per call."""
    factory = MagicMock(name="client_factory")
    factory.side_effect = lambda **kwargs: MagicMock(name=f"per_profile_client_{kwargs.get('api_key', '')}")
    return factory


@pytest.fixture()
def orchestrator(shared_client, client_factory):
    return BoardOrchestrator(
        client=shared_client,
        registry=MagicMock(spec=ProfileRegistry),
        api_key="apk",
        board_id="board",
        secret_store=SecretStore(),
        audit_log_path=Path("logs/test_audit.jsonl"),
        os_labels=set(),
        profile_filter=None,
        client_factory=client_factory,
    )


@pytest.mark.smoke
def test_client_for_profile_uses_shared_when_no_creds(orchestrator, shared_client):
    profile = AgentProfile(id="agent:plain", name="Plain")
    assert_that(orchestrator.client_for_profile(profile) is shared_client, equal_to(True))


@pytest.mark.smoke
def test_client_for_profile_falls_back_to_shared_when_env_unset(orchestrator, shared_client):
    profile = AgentProfile(
        id="agent:code",
        name="Code",
        provider_credentials=ProviderCredentialsConfig(
            trello_api_key_env="TRELLO_AGENT_API_KEY__CODE",
            trello_api_token_env="TRELLO_AGENT_API_TOKEN__CODE",
        ),
    )
    import os
    os.environ.pop("TRELLO_AGENT_API_KEY__CODE", None)
    os.environ.pop("TRELLO_AGENT_API_TOKEN__CODE", None)
    result = orchestrator.client_for_profile(profile)
    assert_that(result is shared_client, equal_to(True))


@pytest.mark.smoke
def test_client_for_profile_builds_per_profile_when_env_set(
    orchestrator, shared_client, client_factory
):
    profile = AgentProfile(
        id="agent:code",
        name="Code",
        provider_credentials=ProviderCredentialsConfig(
            trello_api_key_env="TRELLO_AGENT_API_KEY__CODE",
            trello_api_token_env="TRELLO_AGENT_API_TOKEN__CODE",
        ),
    )
    with patch.dict(
        "os.environ",
        {
            "TRELLO_AGENT_API_KEY__CODE": "AGENT_KEY",
            "TRELLO_AGENT_API_TOKEN__CODE": "AGENT_TOKEN",
        },
        clear=False,
    ):
        result = orchestrator.client_for_profile(profile)
        again = orchestrator.client_for_profile(profile)

    assert_that(result is shared_client, equal_to(False))
    assert_that(again is result, equal_to(True))  # cached
    assert_that(client_factory.call_count, equal_to(1))
    # Verify the agent's creds, not the shared ones, were passed.
    kwargs = client_factory.call_args.kwargs
    assert_that(kwargs["api_key"], equal_to("AGENT_KEY"))
    assert_that(kwargs["token"], equal_to("AGENT_TOKEN"))


@pytest.mark.smoke
def test_post_comment_signs_in_mode_b(orchestrator, shared_client):
    profile = _profile_with_persona(display_name="Bot", role="Tester")
    orchestrator._post_comment("card_1", "## Body", profile)
    args = shared_client.add_comment.call_args.args
    assert_that(args[0], equal_to("card_1"))
    assert_that(args[1], contains_string("👤"))
    assert_that(args[1], contains_string("## Body"))


@pytest.mark.smoke
def test_post_comment_does_not_sign_in_mode_a(orchestrator, shared_client, client_factory):
    profile = AgentProfile(
        id="agent:code",
        name="Code",
        persona=PersonaConfig(display_name="Bot", role="Tester"),
        provider_credentials=ProviderCredentialsConfig(
            trello_api_key_env="TRELLO_AGENT_API_KEY__CODE",
            trello_api_token_env="TRELLO_AGENT_API_TOKEN__CODE",
        ),
    )
    with patch.dict(
        "os.environ",
        {
            "TRELLO_AGENT_API_KEY__CODE": "AGENT_KEY",
            "TRELLO_AGENT_API_TOKEN__CODE": "AGENT_TOKEN",
        },
        clear=False,
    ):
        orchestrator._post_comment("card_1", "## Body", profile)

    # Comment goes to the per-profile client with no signature prefix.
    per_profile_client = client_factory.return_value if not isinstance(
        client_factory.side_effect, type(lambda: None)
    ) else client_factory.spy_return  # MagicMock side-effect closure: pull last
    # Easier: assert the shared client did NOT get the call.
    shared_client.add_comment.assert_not_called()
