"""
apps/antropic/provider.py

Resolve which Anthropic auth path to use. API-key is the primary path for all
programmatic use; Max is interactive-only and opt-in.

This is the shared helper consumed by:
  * the kanban orchestrator (``agents/projects/``) — at orchestrator boot
  * ``BaseApiServiceAnthropic`` (``apps/antropic/references/web/``) — every
    workflow Anthropic call inherits the same detection

Two providers are supported:

  * ``anthropic_api`` — classic ``x-api-key`` auth. Bills against the
    Anthropic Console org that owns the key, under the commercial API terms.
    This is the correct, **primary** path for ALL programmatic / automated
    use (workflow tasks, scheduled jobs, the kanban orchestrator).
    Token source: ``ANTHROPIC_API_KEY``.

  * ``claude_code`` — bearer-token auth using a long-lived Claude Code OAuth
    token, authenticating a *consumer* Claude Max subscription. Max is
    licensed for INTERACTIVE Claude Code use; routing unattended/automated
    traffic through it is outside its intended use. This path is therefore
    only selected when the operator opts in explicitly (see precedence) or
    when it is the only credential present on the host.
    Token source: ``CLAUDE_CODE_OAUTH_TOKEN`` env var, produced once by
    ``claude setup-token`` on a Max-logged-in machine.

Precedence (first match wins):

    1. ``ANTHROPIC_PROVIDER`` (or legacy ``KANBAN_PROVIDER``) explicit
       override (``claude_code`` / ``anthropic_api``). Errors if the required
       credential for that provider is missing — no silent fallback when the
       operator was explicit. Use ``claude_code`` here to deliberately route
       an interactive session through Max.
    2. ``ANTHROPIC_API_KEY`` is set → ``anthropic_api``. This is the default
       for all programmatic use and is chosen even when a Max token is also
       present in the environment.
    3. ``CLAUDE_CODE_OAUTH_TOKEN`` is set and no API key → ``claude_code``,
       with a warning that a consumer subscription is being used for
       programmatic calls.
    4. Hard error with instructions.

Automatic Max → API fallback is wired ONLY for the explicit ``claude_code``
override path (a human who opted into Max but still wants resilience): when an
API key is also present, the resolved Max config carries a ``fallback``
``ProviderConfig`` pointing at the API path that callers can swap to on
usage-limit / rate-limit errors. The fallback is one-directional: Max → API,
never API → Max (Max is a different account, not a higher-capacity tier).
Auto-detected API selection carries no fallback — an automated job must never
silently bill the Max plan.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass, replace
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

    ``fallback`` is set only on the explicit ``claude_code`` override path
    when an API key is also present — callers can swap to it on usage-limit /
    rate-limit errors. Always points one direction: Max (claude_code) → API
    (anthropic_api). Auto-detected API selection never carries a fallback.
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
        probe_cli: Accepted for backward compatibility and ignored. Earlier
                   versions probed the local ``claude`` CLI to nudge the
                   operator toward billing runs against a Max subscription;
                   that nudge was removed because routing automated traffic
                   through a consumer Max plan is outside its intended use.

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

    # Auto-detect. The API key is the primary credential for all programmatic
    # use: it bills the Anthropic Console org under the commercial API terms.
    # It is chosen even when a Max OAuth token is also present, and carries no
    # automatic fallback — an unattended job must never silently bill the
    # consumer Max plan. To deliberately route an interactive session through
    # Max, set ANTHROPIC_PROVIDER=claude_code (handled in the override block).
    if api_key:
        return _build_api(api_key, source=f"{ENV_API_KEY} env")

    if max_token:
        # No API key configured at all. Resolve to Max so the host still
        # works, but warn: routing automated/programmatic calls through a
        # consumer Max subscription is outside its intended (interactive) use.
        logger.warning(
            "provider: only %s is set — resolving to the Claude Max consumer "
            "subscription. Max is intended for interactive Claude Code use; "
            "set %s to bill the Anthropic API for automated/programmatic calls "
            "(recommended to stay within Anthropic's usage terms).",
            ENV_MAX_TOKEN, ENV_API_KEY,
        )
        return _build_max(max_token, source=f"{ENV_MAX_TOKEN} env")

    raise ProviderResolutionError(
        f"No Anthropic credential found. Set one of:\n"
        f"  - {ENV_MAX_TOKEN}   (Claude Max — run `claude setup-token`)\n"
        f"  - {ENV_API_KEY}     (Anthropic Console API key)\n"
        f"Or set {ENV_PROVIDER_OVERRIDE} to force a specific path."
    )


def scrub_competing_env(cfg: ProviderConfig, env: Optional[dict] = None) -> list[str]:
    """Remove competing-credential env vars from the process env after detection.

    The Anthropic Python SDK reads ``ANTHROPIC_API_KEY`` from ``os.environ``
    whenever its ``api_key`` constructor arg is left at the default ``None``.
    Code that builds the client with ``Anthropic(auth_token=<max>)`` and
    forgets to also pass ``api_key=None`` will silently end up with BOTH
    auth headers on every request — and Anthropic's gateway honours
    ``X-Api-Key`` first, billing the Console org instead of Max.

    The fix at the construction site is fragile (every callsite has to
    remember). The robust fix is to ensure that *if* Max is the chosen
    primary, ``ANTHROPIC_API_KEY`` is no longer reachable from the SDK's
    env-fallback path. The fallback ``ProviderConfig`` keeps its captured
    ``api_key`` value in the dataclass, so code that explicitly switches
    on quota error can still build an API-key client — only the implicit
    env channel is closed.

    Symmetry: when ``anthropic_api`` is the chosen primary we also drop
    any stray ``CLAUDE_CODE_OAUTH_TOKEN`` in env, so subprocess tools
    (Bash, MCP) inherited from the parent don't reach for a Max session
    that the orchestrator deliberately rejected.

    Returns the list of env-var names that were actually removed (useful
    for tests and audit logs). Safe to call repeatedly.
    """
    e = env if env is not None else os.environ
    removed: list[str] = []
    if cfg.kind == PROVIDER_CLAUDE_CODE:
        if ENV_API_KEY in e:
            del e[ENV_API_KEY]
            removed.append(ENV_API_KEY)
    elif cfg.kind == PROVIDER_ANTHROPIC_API:
        if ENV_MAX_TOKEN in e:
            del e[ENV_MAX_TOKEN]
            removed.append(ENV_MAX_TOKEN)
    return removed


def log_chosen_provider(cfg: ProviderConfig) -> None:
    """Single log line on boot — makes the routing decision visible without
    having to inspect env at runtime.

    Also scrubs the competing-credential env var from ``os.environ`` so the
    Anthropic SDK can't silently env-fallback to it (see
    ``scrub_competing_env`` for the full rationale).
    """
    logger.info("Anthropic provider resolved: %s", cfg.describe())
    removed = scrub_competing_env(cfg)
    if removed:
        logger.info(
            "Anthropic provider: scrubbed %s from os.environ to prevent SDK "
            "env-fallback (chosen=%s; fallback still reachable via "
            "ProviderConfig.fallback.api_key when wired)",
            ", ".join(removed), cfg.kind,
        )
    if cfg.kind == PROVIDER_CLAUDE_CODE and cfg.fallback is None:
        logger.info(
            "Note: this run is authenticated against a consumer Claude Max "
            "subscription, which is intended for interactive Claude Code use. "
            "For automated/programmatic workloads set ANTHROPIC_API_KEY so "
            "calls bill the Anthropic API (this also enables Max -> API "
            "fallback when Max is chosen via ANTHROPIC_PROVIDER=claude_code)."
        )
