"""
agents/projects/agent/provider.py

Resolve which Anthropic auth path to use at orchestrator boot time.

Two providers are supported:

  * ``claude_code``  — bearer-token auth using a long-lived Claude Code OAuth
    token. Bills against the host's logged-in Claude Max subscription.
    Token source: ``CLAUDE_CODE_OAUTH_TOKEN`` env var, produced once by
    ``claude setup-token`` on a Max-logged-in machine.

  * ``anthropic_api`` — classic ``x-api-key`` auth. Bills against the
    Anthropic Console org that owns the key.
    Token source: ``ANTHROPIC_API_KEY``.

Precedence (first match wins):

    1. ``KANBAN_PROVIDER`` env var explicit override (``claude_code`` /
       ``anthropic_api``). Errors if the required credential for that
       provider is missing — no silent fallback when the operator was
       explicit.
    2. ``CLAUDE_CODE_OAUTH_TOKEN`` is set in the environment → ``claude_code``.
    3. ``ANTHROPIC_API_KEY`` is set in the environment → ``anthropic_api``.
    4. Hard error with instructions.

Both credentials feed the same ``anthropic.Anthropic(...)`` client — the
existing ``BaseKanbanAgent`` tool-use loop runs unchanged regardless of
which provider was resolved.

A *soft* probe runs ``claude --status`` to surface a hint when the user
appears to be Max-logged-in but hasn't generated a programmatic token
yet ("you look logged in to Claude Max — run `claude setup-token` to
bill kanban runs against Max instead of your API key"). The probe never
changes the resolution; it just logs.
"""

from __future__ import annotations

import logging
import os
import shutil
import subprocess
from dataclasses import dataclass
from typing import Optional

logger = logging.getLogger(__name__)

ENV_PROVIDER_OVERRIDE = "KANBAN_PROVIDER"
ENV_MAX_TOKEN = "CLAUDE_CODE_OAUTH_TOKEN"
ENV_API_KEY = "ANTHROPIC_API_KEY"

PROVIDER_CLAUDE_CODE = "claude_code"
PROVIDER_ANTHROPIC_API = "anthropic_api"

_VALID_PROVIDERS = (PROVIDER_CLAUDE_CODE, PROVIDER_ANTHROPIC_API)


class ProviderResolutionError(RuntimeError):
    """No usable Anthropic credential found, or an explicit override was
    requested but its credential is missing."""


@dataclass(frozen=True)
class ProviderConfig:
    """The resolved authentication route. Pass to ``BaseKanbanAgent``.

    Exactly one of ``api_key`` / ``auth_token`` is set, matching ``kind``.
    """

    kind: str            # PROVIDER_CLAUDE_CODE or PROVIDER_ANTHROPIC_API
    api_key: Optional[str] = None
    auth_token: Optional[str] = None
    source: str = ""     # human-readable, used in logs / audit
    billing_hint: str = ""  # short label e.g. "Claude Max subscription"

    def describe(self) -> str:
        return f"{self.kind} (source: {self.source}; billing: {self.billing_hint})"

    def inject_into(self, scoped: dict) -> None:
        """Add the right credential under the right env-var name to a scoped
        secrets dict that gets handed to subprocess-tool environments
        (Bash, MCP servers, etc).

        ``claude_code`` → ``CLAUDE_CODE_OAUTH_TOKEN`` (subprocess tools use the
                          same Max session).
        ``anthropic_api`` → ``ANTHROPIC_API_KEY``.

        Existing keys in ``scoped`` are never overwritten — a profile that
        explicitly requires its own ``ANTHROPIC_API_KEY`` (or token) keeps it.
        """
        if self.kind == PROVIDER_CLAUDE_CODE:
            if self.auth_token and ENV_MAX_TOKEN not in scoped:
                scoped[ENV_MAX_TOKEN] = self.auth_token
        else:
            if self.api_key and ENV_API_KEY not in scoped:
                scoped[ENV_API_KEY] = self.api_key


def _read_env(name: str) -> str:
    """Read an env var, treating empty string as unset."""
    val = os.environ.get(name, "")
    return val.strip()


def _claude_cli_max_hint() -> Optional[str]:
    """Best-effort probe to detect a Max-logged-in `claude` CLI session.

    Returns a short hint string when the user appears Max-authenticated
    but hasn't generated a programmatic token, otherwise None.

    Never raises; never affects resolution — purely informational.
    """
    claude_path = shutil.which("claude")
    if not claude_path:
        return None
    try:
        result = subprocess.run(
            [claude_path, "--status"],
            capture_output=True,
            text=True,
            timeout=5,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if result.returncode != 0:
        return None
    blob = (result.stdout + "\n" + result.stderr).lower()
    looks_logged_in = "logged in" in blob or "authenticated" in blob
    looks_like_max = "max" in blob or "oauth" in blob or "subscription" in blob
    if looks_logged_in and looks_like_max:
        return (
            "`claude` CLI appears to be Max-logged-in but "
            "CLAUDE_CODE_OAUTH_TOKEN is not set. Run `claude setup-token` "
            "once to bill kanban runs against your Max quota."
        )
    return None


def _build_max(token: str, source: str) -> ProviderConfig:
    return ProviderConfig(
        kind=PROVIDER_CLAUDE_CODE,
        auth_token=token,
        source=source,
        billing_hint="Claude Max subscription",
    )


def _build_api(key: str, source: str) -> ProviderConfig:
    return ProviderConfig(
        kind=PROVIDER_ANTHROPIC_API,
        api_key=key,
        source=source,
        billing_hint="Anthropic Console API key",
    )


def detect_provider(
    env: Optional[dict[str, str]] = None,
    *,
    probe_cli: bool = True,
) -> ProviderConfig:
    """Resolve the auth path. See module docstring for precedence rules.

    Args:
        env: Optional environment override (defaults to ``os.environ``).
             Used by tests to inject a clean env without touching the
             process env.
        probe_cli: When True (default), also probe ``claude --status`` to
                   log a soft hint when Max appears logged in but no
                   programmatic token is set. Disabled in tests.

    Raises:
        ProviderResolutionError: when no usable credential is configured.
    """
    e = env if env is not None else os.environ
    get = lambda name: (e.get(name) or "").strip()  # noqa: E731

    override = get(ENV_PROVIDER_OVERRIDE).lower()
    max_token = get(ENV_MAX_TOKEN)
    api_key = get(ENV_API_KEY)

    if override:
        if override not in _VALID_PROVIDERS:
            raise ProviderResolutionError(
                f"{ENV_PROVIDER_OVERRIDE}={override!r} is not one of "
                f"{_VALID_PROVIDERS}. Unset it or pick a valid value."
            )
        if override == PROVIDER_CLAUDE_CODE:
            if not max_token:
                raise ProviderResolutionError(
                    f"{ENV_PROVIDER_OVERRIDE}=claude_code requires "
                    f"{ENV_MAX_TOKEN} to be set. Run `claude setup-token` "
                    f"on a Max-logged-in machine and export the result."
                )
            return _build_max(max_token, source=f"{ENV_PROVIDER_OVERRIDE} override")
        # override == anthropic_api
        if not api_key:
            raise ProviderResolutionError(
                f"{ENV_PROVIDER_OVERRIDE}=anthropic_api requires "
                f"{ENV_API_KEY} to be set."
            )
        return _build_api(api_key, source=f"{ENV_PROVIDER_OVERRIDE} override")

    if max_token:
        return _build_max(max_token, source=f"{ENV_MAX_TOKEN} env")

    if api_key:
        if probe_cli:
            hint = _claude_cli_max_hint()
            if hint:
                logger.info("provider: %s", hint)
        return _build_api(api_key, source=f"{ENV_API_KEY} env")

    raise ProviderResolutionError(
        f"No Anthropic credential found. Set one of:\n"
        f"  - {ENV_MAX_TOKEN}   (Claude Max — run `claude setup-token`)\n"
        f"  - {ENV_API_KEY}     (Anthropic Console API key)\n"
        f"Or set {ENV_PROVIDER_OVERRIDE} to force a specific path."
    )


def log_chosen_provider(cfg: ProviderConfig) -> None:
    """Single log line on orchestrator boot — makes the routing decision
    visible without having to inspect env at runtime."""
    logger.info("Kanban provider resolved: %s", cfg.describe())
    if cfg.kind == PROVIDER_CLAUDE_CODE:
        logger.info(
            "Note: Claude Max rate limits are lower than API tier. If you "
            "run KANBAN_NUM_AGENTS > 1 you may see 429s during bursts."
        )
