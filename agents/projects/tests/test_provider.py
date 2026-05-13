"""
Unit tests for agents.projects.agent.provider.

All tests pass an explicit `env` dict and `probe_cli=False` so nothing
touches the host environment or the real `claude` binary.
"""

from __future__ import annotations

import pytest

from agents.projects.agent.provider import (
    ENV_API_KEY,
    ENV_MAX_TOKEN,
    ENV_PROVIDER_OVERRIDE,
    PROVIDER_ANTHROPIC_API,
    PROVIDER_CLAUDE_CODE,
    ProviderConfig,
    ProviderResolutionError,
    detect_provider,
)


# ── auto-detect precedence ────────────────────────────────────────────────────

def test_max_token_alone_resolves_to_claude_code():
    cfg = detect_provider(env={ENV_MAX_TOKEN: "oauth-xyz"}, probe_cli=False)
    assert cfg.kind == PROVIDER_CLAUDE_CODE
    assert cfg.auth_token == "oauth-xyz"
    assert cfg.api_key is None
    assert "Max" in cfg.billing_hint


def test_api_key_alone_resolves_to_anthropic_api():
    cfg = detect_provider(env={ENV_API_KEY: "sk-abc"}, probe_cli=False)
    assert cfg.kind == PROVIDER_ANTHROPIC_API
    assert cfg.api_key == "sk-abc"
    assert cfg.auth_token is None


def test_max_wins_when_both_credentials_are_set():
    """Default auto-detect prefers Max over API — that's the whole point of
    the feature ("if Claude Max is available use that, else API key")."""
    cfg = detect_provider(
        env={ENV_MAX_TOKEN: "oauth-xyz", ENV_API_KEY: "sk-abc"},
        probe_cli=False,
    )
    assert cfg.kind == PROVIDER_CLAUDE_CODE


def test_empty_string_treated_as_unset():
    """Empty strings in env (common after `export FOO=`) must not register."""
    cfg = detect_provider(
        env={ENV_MAX_TOKEN: "", ENV_API_KEY: "sk-abc"},
        probe_cli=False,
    )
    assert cfg.kind == PROVIDER_ANTHROPIC_API


def test_no_credentials_raises():
    with pytest.raises(ProviderResolutionError) as ei:
        detect_provider(env={}, probe_cli=False)
    msg = str(ei.value)
    assert ENV_MAX_TOKEN in msg
    assert ENV_API_KEY in msg


# ── explicit override ─────────────────────────────────────────────────────────

def test_override_claude_code_with_token():
    cfg = detect_provider(
        env={
            ENV_PROVIDER_OVERRIDE: "claude_code",
            ENV_MAX_TOKEN: "oauth-xyz",
            ENV_API_KEY: "sk-abc",
        },
        probe_cli=False,
    )
    assert cfg.kind == PROVIDER_CLAUDE_CODE
    assert "override" in cfg.source


def test_override_anthropic_api_wins_over_max_token():
    """If you set KANBAN_PROVIDER=anthropic_api the operator was explicit —
    the Max token is ignored."""
    cfg = detect_provider(
        env={
            ENV_PROVIDER_OVERRIDE: "anthropic_api",
            ENV_MAX_TOKEN: "oauth-xyz",
            ENV_API_KEY: "sk-abc",
        },
        probe_cli=False,
    )
    assert cfg.kind == PROVIDER_ANTHROPIC_API


def test_override_claude_code_without_token_raises():
    with pytest.raises(ProviderResolutionError) as ei:
        detect_provider(
            env={ENV_PROVIDER_OVERRIDE: "claude_code", ENV_API_KEY: "sk-abc"},
            probe_cli=False,
        )
    assert ENV_MAX_TOKEN in str(ei.value)


def test_override_anthropic_api_without_key_raises():
    with pytest.raises(ProviderResolutionError) as ei:
        detect_provider(
            env={ENV_PROVIDER_OVERRIDE: "anthropic_api", ENV_MAX_TOKEN: "x"},
            probe_cli=False,
        )
    assert ENV_API_KEY in str(ei.value)


def test_invalid_override_raises():
    with pytest.raises(ProviderResolutionError):
        detect_provider(
            env={ENV_PROVIDER_OVERRIDE: "bogus", ENV_API_KEY: "sk-abc"},
            probe_cli=False,
        )


def test_override_is_case_insensitive():
    cfg = detect_provider(
        env={
            ENV_PROVIDER_OVERRIDE: "CLAUDE_CODE",
            ENV_MAX_TOKEN: "oauth-xyz",
        },
        probe_cli=False,
    )
    assert cfg.kind == PROVIDER_CLAUDE_CODE


# ── inject_into() ─────────────────────────────────────────────────────────────

def test_inject_into_max_sets_oauth_token():
    cfg = ProviderConfig(kind=PROVIDER_CLAUDE_CODE, auth_token="oauth-xyz")
    scoped: dict = {}
    cfg.inject_into(scoped)
    assert scoped == {ENV_MAX_TOKEN: "oauth-xyz"}


def test_inject_into_api_sets_api_key():
    cfg = ProviderConfig(kind=PROVIDER_ANTHROPIC_API, api_key="sk-abc")
    scoped: dict = {}
    cfg.inject_into(scoped)
    assert scoped == {ENV_API_KEY: "sk-abc"}


def test_inject_into_does_not_overwrite():
    """Profile-supplied credentials win — the orchestrator only fills gaps."""
    cfg = ProviderConfig(kind=PROVIDER_ANTHROPIC_API, api_key="sk-orch")
    scoped = {ENV_API_KEY: "sk-profile-explicit"}
    cfg.inject_into(scoped)
    assert scoped[ENV_API_KEY] == "sk-profile-explicit"


# ── describe() — used in audit/log ────────────────────────────────────────────

def test_describe_contains_kind_and_source():
    cfg = detect_provider(env={ENV_MAX_TOKEN: "oauth-xyz"}, probe_cli=False)
    desc = cfg.describe()
    assert PROVIDER_CLAUDE_CODE in desc
    assert ENV_MAX_TOKEN in desc
    assert "Max" in desc
