"""
apps/antropic/provider.py

Resolve which Anthropic auth path to use, with optional Max → API fallback.

This is the shared helper consumed by:
  * the kanban orchestrator (``agents/projects/``) — at orchestrator boot
  * ``BaseApiServiceAnthropic`` (``apps/antropic/references/web/``) — every
    workflow Anthropic call inherits the same detection

Two providers are supported:

  * ``claude_code``  — bearer-token auth using a long-lived Claude Code OAuth
    token. Bills against the host's logged-in Claude Max subscription.
    Token source: ``CLAUDE_CODE_OAUTH_TOKEN`` env var, produced once by
    ``claude setup-token`` on a Max-logged-in machine.

  * ``anthropic_api`` — classic ``x-api-key`` auth. Bills against the
    Anthropic Console org that owns the key.
    Token source: ``ANTHROPIC_API_KEY``.

Precedence (first match wins):

    1. ``ANTHROPIC_PROVIDER`` (or legacy ``KANBAN_PROVIDER``) explicit
       override (``claude_code`` / ``anthropic_api``). Errors if the required
       credential for that provider is missing — no silent fallback when the
       operator was explicit.
    2. ``CLAUDE_CODE_OAUTH_TOKEN`` is set → ``claude_code``.
    3. ``ANTHROPIC_API_KEY`` is set → ``anthropic_api``.
    4. Hard error with instructions.

When BOTH credentials are present, the resolved primary (Max) carries a
``fallback`` ``ProviderConfig`` pointing at the API path — callers (the
kanban agent loop, and any workflow task that wants resilience) can swap
to it on usage-limit / rate-limit errors. The fallback is intentionally
one-directional: Max → API, never API → Max (Max is a different account,
not a higher-capacity tier).

A *soft* probe runs ``claude --status`` to log a hint when the user
appears to be Max-logged-in but hasn't generated a programmatic token
("you look logged in to Claude Max — run `claude setup-token` to bill
runs against Max instead of your API key"). The probe never changes the
resolution; it just logs.
"""

from __future__ import annotations

import logging
import os
import shutil
import subprocess
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

# Canonical env var; ``KANBAN_PROVIDER`` is kept as a back-compat alias.
ENV_PROVIDER_OVERRIDE = "ANTHROPIC_PROVIDER"
ENV_PROVIDER_OVERRIDE_LEGACY = "KANBAN_PROVIDER"
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
    """The resolved authentication route.

    Exactly one of ``api_key`` / ``auth_token`` is set, matching ``kind``.

    ``fallback`` is set when *both* a Max token and an API key were present
    in the environment at detection time — callers can swap to it on
    usage-limit / rate-limit errors. Always points one direction:
    Max (claude_code) → API (anthropic_api).
    """

    kind: str            # PROVIDER_CLAUDE_CODE or PROVIDER_ANTHROPIC_API
    api_key: Optional[str] = None
    auth_token: Optional[str] = None
    source: str = ""     # human-readable, used in logs / audit
    billing_hint: str = ""  # short label e.g. "Claude Max subscription"
    fallback: Optional["ProviderConfig"] = None

    def describe(self) -> str:
        base = f"{self.kind} (source: {self.source}; billing: {self.billing_hint})"
        if self.fallback:
            base += f" [fallback ready: {self.fallback.kind}]"
        return base

    def short_label(self) -> str:
        """One-line label suitable for status displays and Trello comments.

        Examples:
            "Claude Max subscription"
            "Anthropic API key"
            "Claude Max subscription (→ Anthropic API fallback ready)"
        """
        primary = self.billing_hint or self.kind
        if self.fallback:
            fb = self.fallback.billing_hint or self.fallback.kind
            return f"{primary} (→ {fb} fallback ready)"
        return primary

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


def _claude_cli_max_hint(home: Optional[Path] = None) -> Optional[str]:
    """Best-effort heuristic: is the `claude` CLI installed and used interactively?

    Returns a hint string when the CLI is present AND there's evidence the
    user has run it (a populated ``~/.claude/`` directory). The caller uses
    this to nudge the operator: "you may have a Max session — run
    ``claude setup-token`` to share that billing with workflows".

    We cannot reliably detect *Max specifically* without the keychain —
    Claude Code stores OAuth credentials there on macOS and there is no
    non-interactive query. So the hint is conservative: it tells the user
    a token is worth generating IF they have Max, rather than claiming we
    detected Max. The old probe shelled out to ``claude --status`` which
    is not a real flag, so the hint never fired.

    Never raises; never affects resolution.
    """
    claude_path = shutil.which("claude")
    if not claude_path:
        return None
    # Confirm the binary is the real Claude Code CLI, not some unrelated
    # `claude` on PATH. A successful ``--version`` is enough — its output
    # mentions "Claude Code".
    try:
        ver = subprocess.run(
            [claude_path, "--version"],
            capture_output=True, text=True, timeout=5,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if ver.returncode != 0 or "claude" not in (ver.stdout + ver.stderr).lower():
        return None

    home_dir = home or Path.home() / ".claude"
    # `~/.claude/projects` or `history.jsonl` only get populated by interactive
    # sessions — their presence is a strong signal the user actually uses the
    # CLI on this machine (vs. it just being installed system-wide).
    interactive_signal = (
        (home_dir / "projects").is_dir() or (home_dir / "history.jsonl").exists()
    )
    if not interactive_signal:
        return None

    return (
        f"`claude` CLI is installed ({ver.stdout.strip() or 'version unknown'}) "
        f"and has interactive state at {home_dir}. If this machine has an "
        f"active Claude Max subscription, run `claude setup-token` and export "
        f"the result as CLAUDE_CODE_OAUTH_TOKEN to bill runs against Max "
        f"instead of your API key."
    )


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
    env: Optional[dict] = None,
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

    override = (get(ENV_PROVIDER_OVERRIDE) or get(ENV_PROVIDER_OVERRIDE_LEGACY)).lower()
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
            cfg = _build_max(max_token, source=f"{ENV_PROVIDER_OVERRIDE} override")
            # Even when overridden to Max, attach an API fallback if available.
            if api_key:
                cfg = replace(
                    cfg,
                    fallback=_build_api(api_key, source="fallback after Max quota"),
                )
            return cfg
        # override == anthropic_api
        if not api_key:
            raise ProviderResolutionError(
                f"{ENV_PROVIDER_OVERRIDE}=anthropic_api requires "
                f"{ENV_API_KEY} to be set."
            )
        return _build_api(api_key, source=f"{ENV_PROVIDER_OVERRIDE} override")

    if max_token:
        cfg = _build_max(max_token, source=f"{ENV_MAX_TOKEN} env")
        if api_key:
            cfg = replace(
                cfg,
                fallback=_build_api(api_key, source="fallback after Max quota"),
            )
        return cfg

    if api_key:
        cfg = _build_api(api_key, source=f"{ENV_API_KEY} env")
        if probe_cli:
            hint = _claude_cli_max_hint()
            if hint:
                # Louder than info() — this is the case where the operator
                # is silently paying API rates while a Max subscription may
                # be sitting unused on the same machine.
                logger.warning("provider: %s", hint)
                cfg = replace(cfg, billing_hint=cfg.billing_hint + " (Max available — unused)")
        return cfg

    raise ProviderResolutionError(
        f"No Anthropic credential found. Set one of:\n"
        f"  - {ENV_MAX_TOKEN}   (Claude Max — run `claude setup-token`)\n"
        f"  - {ENV_API_KEY}     (Anthropic Console API key)\n"
        f"Or set {ENV_PROVIDER_OVERRIDE} to force a specific path."
    )


def log_chosen_provider(cfg: ProviderConfig) -> None:
    """Single log line on boot — makes the routing decision visible without
    having to inspect env at runtime."""
    logger.info("Anthropic provider resolved: %s", cfg.describe())
    if cfg.kind == PROVIDER_CLAUDE_CODE and cfg.fallback is None:
        logger.info(
            "Note: Claude Max rate limits are lower than API tier. If you "
            "hit a quota error there is no fallback configured — set "
            "ANTHROPIC_API_KEY to enable Max -> API fallback."
        )
