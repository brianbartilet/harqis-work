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
    ENV_PROVIDER_OVERRIDE_LEGACY,
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


# ── Max → API fallback wiring ─────────────────────────────────────────────────

def test_both_credentials_attaches_api_fallback_to_max_primary():
    """When both creds are set the primary is Max with an API fallback —
    that's how the agent loop knows to swap on quota errors."""
    cfg = detect_provider(
        env={ENV_MAX_TOKEN: "oauth-xyz", ENV_API_KEY: "sk-abc"},
        probe_cli=False,
    )
    assert cfg.kind == PROVIDER_CLAUDE_CODE
    assert cfg.fallback is not None
    assert cfg.fallback.kind == PROVIDER_ANTHROPIC_API
    assert cfg.fallback.api_key == "sk-abc"
    # Fallback is one-directional — the API fallback has no further fallback.
    assert cfg.fallback.fallback is None


def test_max_only_has_no_fallback():
    cfg = detect_provider(env={ENV_MAX_TOKEN: "oauth-xyz"}, probe_cli=False)
    assert cfg.kind == PROVIDER_CLAUDE_CODE
    assert cfg.fallback is None


def test_api_only_has_no_fallback():
    cfg = detect_provider(env={ENV_API_KEY: "sk-abc"}, probe_cli=False)
    assert cfg.kind == PROVIDER_ANTHROPIC_API
    assert cfg.fallback is None


def test_explicit_max_override_still_attaches_fallback_when_api_key_present():
    """Even when forced to Max, having an API key in env means fallback is
    available — this is the "I picked Max but want resilience" case."""
    cfg = detect_provider(
        env={
            ENV_PROVIDER_OVERRIDE: "claude_code",
            ENV_MAX_TOKEN: "oauth-xyz",
            ENV_API_KEY: "sk-abc",
        },
        probe_cli=False,
    )
    assert cfg.kind == PROVIDER_CLAUDE_CODE
    assert cfg.fallback is not None
    assert cfg.fallback.kind == PROVIDER_ANTHROPIC_API


def test_explicit_api_override_does_not_attach_max_fallback():
    """Fallback is intentionally one-directional. API → Max would be wrong
    because Max is a different account, not a higher-capacity tier."""
    cfg = detect_provider(
        env={
            ENV_PROVIDER_OVERRIDE: "anthropic_api",
            ENV_MAX_TOKEN: "oauth-xyz",
            ENV_API_KEY: "sk-abc",
        },
        probe_cli=False,
    )
    assert cfg.kind == PROVIDER_ANTHROPIC_API
    assert cfg.fallback is None


def test_describe_mentions_fallback_when_present():
    cfg = detect_provider(
        env={ENV_MAX_TOKEN: "oauth-xyz", ENV_API_KEY: "sk-abc"},
        probe_cli=False,
    )
    assert "fallback ready" in cfg.describe()


# ── legacy KANBAN_PROVIDER alias ──────────────────────────────────────────────

def test_legacy_kanban_provider_alias_works():
    """KANBAN_PROVIDER is kept as a back-compat alias for ANTHROPIC_PROVIDER."""
    cfg = detect_provider(
        env={ENV_PROVIDER_OVERRIDE_LEGACY: "anthropic_api", ENV_API_KEY: "sk-abc"},
        probe_cli=False,
    )
    assert cfg.kind == PROVIDER_ANTHROPIC_API


def test_canonical_provider_var_wins_over_legacy():
    """When both are set the canonical ANTHROPIC_PROVIDER takes precedence."""
    cfg = detect_provider(
        env={
            ENV_PROVIDER_OVERRIDE: "anthropic_api",
            ENV_PROVIDER_OVERRIDE_LEGACY: "claude_code",
            ENV_API_KEY: "sk-abc",
            ENV_MAX_TOKEN: "oauth-xyz",
        },
        probe_cli=False,
    )
    assert cfg.kind == PROVIDER_ANTHROPIC_API
