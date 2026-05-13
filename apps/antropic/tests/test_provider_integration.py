"""
Unit tests for BaseApiServiceAnthropic provider integration.

These tests do not hit the Anthropic API. They construct the service with
controlled env / kwargs and verify the chosen auth path + the Max → API
fallback swap on simulated quota errors.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import patch

import pytest
from anthropic import APIStatusError, RateLimitError

from apps.antropic.provider import (
    ENV_API_KEY,
    ENV_MAX_TOKEN,
    PROVIDER_ANTHROPIC_API,
    PROVIDER_CLAUDE_CODE,
)
from apps.antropic.references.web.base_api_service import BaseApiServiceAnthropic


def _fake_config(api_data: dict | None = None):
    """Minimal AppConfigWSClient-shaped stand-in."""
    return SimpleNamespace(app_data=api_data or {})


# ── provider detection at construction time ──────────────────────────────────

def test_explicit_api_key_arg_bypasses_detection(monkeypatch):
    """Passing api_key= explicitly skips detect_provider entirely.

    Important: callers that already pin a key in config / kwargs keep
    their behaviour. The Max bearer never sneaks in for those callers.
    """
    monkeypatch.setenv(ENV_MAX_TOKEN, "oauth-xyz")
    monkeypatch.delenv(ENV_API_KEY, raising=False)
    svc = BaseApiServiceAnthropic(_fake_config(), api_key="sk-explicit")
    assert svc.provider_config is None
    assert svc.api_key == "sk-explicit"


def test_max_only_env_uses_bearer_auth(monkeypatch):
    monkeypatch.setenv(ENV_MAX_TOKEN, "oauth-xyz")
    monkeypatch.delenv(ENV_API_KEY, raising=False)
    monkeypatch.delenv("ANTHROPIC_PROVIDER", raising=False)
    monkeypatch.delenv("KANBAN_PROVIDER", raising=False)
    svc = BaseApiServiceAnthropic(_fake_config())
    assert svc.provider_config is not None
    assert svc.provider_config.kind == PROVIDER_CLAUDE_CODE
    assert svc.api_key is None  # bearer path doesn't expose an api_key
    assert svc.base_client is not None
    assert svc.async_client is not None


def test_api_only_env_uses_api_key_auth(monkeypatch):
    monkeypatch.delenv(ENV_MAX_TOKEN, raising=False)
    monkeypatch.setenv(ENV_API_KEY, "sk-env")
    monkeypatch.delenv("ANTHROPIC_PROVIDER", raising=False)
    monkeypatch.delenv("KANBAN_PROVIDER", raising=False)
    svc = BaseApiServiceAnthropic(_fake_config())
    assert svc.provider_config is not None
    assert svc.provider_config.kind == PROVIDER_ANTHROPIC_API
    assert svc.api_key == "sk-env"


def test_both_creds_attaches_fallback(monkeypatch):
    monkeypatch.setenv(ENV_MAX_TOKEN, "oauth-xyz")
    monkeypatch.setenv(ENV_API_KEY, "sk-env")
    monkeypatch.delenv("ANTHROPIC_PROVIDER", raising=False)
    monkeypatch.delenv("KANBAN_PROVIDER", raising=False)
    svc = BaseApiServiceAnthropic(_fake_config())
    assert svc.provider_config.kind == PROVIDER_CLAUDE_CODE
    assert svc.provider_config.fallback is not None
    assert svc.provider_config.fallback.kind == PROVIDER_ANTHROPIC_API


def test_no_creds_does_not_explode(monkeypatch):
    """Legacy fallback: when nothing is configured the service still
    constructs (with api_key=None). It only fails at call time."""
    monkeypatch.delenv(ENV_MAX_TOKEN, raising=False)
    monkeypatch.delenv(ENV_API_KEY, raising=False)
    monkeypatch.delenv("ANTHROPIC_PROVIDER", raising=False)
    monkeypatch.delenv("KANBAN_PROVIDER", raising=False)
    svc = BaseApiServiceAnthropic(_fake_config())
    assert svc.provider_config is None
    assert svc.api_key is None


# ── fallback swap on quota error ─────────────────────────────────────────────

def _make_status_error(status: int, message: str) -> APIStatusError:
    """Build an APIStatusError without hitting the network. The SDK requires
    a request and a response; SimpleNamespace shims are enough for str(exc)."""
    response = SimpleNamespace(
        status_code=status,
        request=SimpleNamespace(),
        headers={},
        text=message,
    )
    body = {"error": {"message": message}}
    if status == 429:
        return RateLimitError(message=message, response=response, body=body)
    return APIStatusError(message=message, response=response, body=body)


def test_swap_on_rate_limit_when_fallback_present(monkeypatch):
    monkeypatch.setenv(ENV_MAX_TOKEN, "oauth-xyz")
    monkeypatch.setenv(ENV_API_KEY, "sk-env")
    monkeypatch.delenv("ANTHROPIC_PROVIDER", raising=False)
    monkeypatch.delenv("KANBAN_PROVIDER", raising=False)
    svc = BaseApiServiceAnthropic(_fake_config())

    exc = _make_status_error(429, "Rate limit exceeded")
    swapped = svc._maybe_swap_to_fallback(exc)
    assert swapped is True
    assert svc.provider_config.kind == PROVIDER_ANTHROPIC_API
    assert svc.api_key == "sk-env"
    # After swap there is no further fallback — a second hit must raise.
    assert svc.provider_config.fallback is None


def test_swap_on_usage_limit_string_match(monkeypatch):
    """400-class APIStatusError with 'usage limit' in the message also
    triggers the swap — that's how Anthropic reports Max-quota exhaustion."""
    monkeypatch.setenv(ENV_MAX_TOKEN, "oauth-xyz")
    monkeypatch.setenv(ENV_API_KEY, "sk-env")
    monkeypatch.delenv("ANTHROPIC_PROVIDER", raising=False)
    monkeypatch.delenv("KANBAN_PROVIDER", raising=False)
    svc = BaseApiServiceAnthropic(_fake_config())

    exc = _make_status_error(400, "You have reached your specified API usage limits.")
    swapped = svc._maybe_swap_to_fallback(exc)
    assert swapped is True
    assert svc.provider_config.kind == PROVIDER_ANTHROPIC_API


def test_no_swap_when_no_fallback(monkeypatch):
    monkeypatch.delenv(ENV_MAX_TOKEN, raising=False)
    monkeypatch.setenv(ENV_API_KEY, "sk-env")
    monkeypatch.delenv("ANTHROPIC_PROVIDER", raising=False)
    monkeypatch.delenv("KANBAN_PROVIDER", raising=False)
    svc = BaseApiServiceAnthropic(_fake_config())

    exc = _make_status_error(429, "Rate limit exceeded")
    swapped = svc._maybe_swap_to_fallback(exc)
    assert swapped is False
    # Config unchanged.
    assert svc.provider_config.kind == PROVIDER_ANTHROPIC_API


def test_no_swap_on_generic_4xx(monkeypatch):
    """A 400 that ISN'T a quota/rate-limit must not trigger the swap —
    we don't want to spend Max calls on actual bad-request bugs."""
    monkeypatch.setenv(ENV_MAX_TOKEN, "oauth-xyz")
    monkeypatch.setenv(ENV_API_KEY, "sk-env")
    monkeypatch.delenv("ANTHROPIC_PROVIDER", raising=False)
    monkeypatch.delenv("KANBAN_PROVIDER", raising=False)
    svc = BaseApiServiceAnthropic(_fake_config())

    exc = _make_status_error(400, "Invalid request: max_tokens out of range")
    swapped = svc._maybe_swap_to_fallback(exc)
    assert swapped is False
    assert svc.provider_config.kind == PROVIDER_CLAUDE_CODE  # unchanged


# ── send_message wraps the swap-and-retry ────────────────────────────────────

def test_send_message_retries_once_on_quota_and_succeeds(monkeypatch):
    """The end-to-end happy path: first call raises a quota error, swap
    happens, second call (on the fallback client) returns successfully."""
    monkeypatch.setenv(ENV_MAX_TOKEN, "oauth-xyz")
    monkeypatch.setenv(ENV_API_KEY, "sk-env")
    monkeypatch.delenv("ANTHROPIC_PROVIDER", raising=False)
    monkeypatch.delenv("KANBAN_PROVIDER", raising=False)
    svc = BaseApiServiceAnthropic(_fake_config())

    calls = {"n": 0}

    def fake_create(**_kwargs):
        calls["n"] += 1
        if calls["n"] == 1:
            raise _make_status_error(429, "Rate limit exceeded")
        return SimpleNamespace(content=[SimpleNamespace(text="ok")])

    # Patch the _with_backoff method to call our fake directly (skips its
    # internal retry loop so we don't burn through max_retries).
    with patch.object(svc, "_with_backoff", side_effect=lambda fn, **kw: fake_create(**kw)):
        result = svc.send_message("ping")

    assert calls["n"] == 2
    assert result.content[0].text == "ok"
    assert svc.provider_config.kind == PROVIDER_ANTHROPIC_API  # swapped
