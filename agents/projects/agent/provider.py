"""
agents/projects/agent/provider.py

Back-compat shim. The implementation moved to ``apps/antropic/provider.py``
so that both the kanban orchestrator and ``BaseApiServiceAnthropic`` (which
every workflow Anthropic call routes through) share the same detection
logic.

New code should import directly from ``apps.antropic.provider``.
"""

from apps.antropic.provider import (  # noqa: F401
    ENV_API_KEY,
    ENV_MAX_TOKEN,
    ENV_PROVIDER_OVERRIDE,
    ENV_PROVIDER_OVERRIDE_LEGACY,
    PROVIDER_ANTHROPIC_API,
    PROVIDER_CLAUDE_CODE,
    ProviderConfig,
    ProviderResolutionError,
    detect_provider,
    log_chosen_provider,
)
