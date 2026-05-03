"""
Elasticsearch telemetry for projects orchestration.

Emits one document per lifecycle event into a dedicated index so the
operations dashboard (Kibana / Grafana) can answer:

  - How many cards processed per board / per profile / per host?
  - Failure rate over time, broken down by failure kind?
  - Time-in-Pending / Time-in-In-Progress distributions?
  - Which agents are paused-for-question right now?

Reuses `harqis-core`'s `core.apps.es_logging.app.elasticsearch.post` so the
auth, URL, proxy, and SSL handling are the same as every other ES doc the
platform writes.

**No-op fallback.** When the harqis-core library is missing OR
`ES_LOGGING` is not configured in `apps_config.yaml`, every emit_* function
returns silently — a host that doesn't run ES still works exactly as before.

**Crash safety.** Every emit catches its own exceptions. A broken ES
connection NEVER stops a card from being processed.
"""

from __future__ import annotations

import logging
import os
import platform
import socket
from datetime import datetime, timezone
from typing import Any, Optional

logger = logging.getLogger(__name__)

# Single index for every projects-orchestrator event. Override per-deploy
# with KANBAN_TELEMETRY_INDEX — useful for dev/prod separation in a shared
# ES cluster.
_DEFAULT_INDEX = "harqis-projects-events"


def _index_name() -> str:
    return os.environ.get("KANBAN_TELEMETRY_INDEX", _DEFAULT_INDEX)


# ── Lazy library import ──────────────────────────────────────────────────────

# `_post` is imported lazily so the harqis-core wheel being absent (or
# unconfigured) just disables emission instead of crashing import. The
# `_es_available` flag is None until the first emit attempt — we don't want
# to import the library if no events ever fire.
_es_post = None  # type: ignore[var-annotated]
_es_available: Optional[bool] = None


def _resolve_es_post():
    """Return `core.apps.es_logging.app.elasticsearch.post` or None.

    Cached after the first call. Side-effect free for the caller — exceptions
    are swallowed and turn into "ES not available".
    """
    global _es_post, _es_available
    if _es_available is not None:
        return _es_post
    try:
        from core.apps.es_logging.app.elasticsearch import post as _post
        _es_post = _post
        _es_available = True
        logger.info("ES telemetry enabled (index=%s)", _index_name())
    except Exception as e:
        # Could be missing dependency, missing config file, or auth failure
        # at config-load time. All paths → silently disable.
        _es_available = False
        logger.info("ES telemetry disabled: %s", e)
    return _es_post


def is_enabled() -> bool:
    """True when `core.apps.es_logging` is importable and configured.

    Safe to call from anywhere — never raises, side-effect is a one-time
    import probe.
    """
    return _resolve_es_post() is not None


# ── Common payload + emit ────────────────────────────────────────────────────

def _host() -> str:
    return socket.gethostname()


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def _base_payload(event: str, **fields: Any) -> dict:
    """Build the common shape attached to every emitted doc."""
    payload = {
        "event": event,
        "ts": _now_iso(),
        "host": _host(),
        "host_os": platform.system().lower(),
    }
    payload.update({k: v for k, v in fields.items() if v is not None})
    return payload


def _emit(event: str, location_key: str, **fields: Any) -> None:
    """Send one document. Crashes here are swallowed and logged at warning."""
    post = _resolve_es_post()
    if post is None:
        return
    try:
        post(
            json_dump=_base_payload(event, **fields),
            index_name=_index_name(),
            location_key=location_key,
            use_interval_map=False,
            identifier=f"{event}_{int(datetime.now(timezone.utc).timestamp() * 1000)}",
        )
    except Exception as e:
        # Never let telemetry tank a card — log and move on.
        logger.warning("ES emit failed for event=%s: %s", event, e)


# ── Public emission API ──────────────────────────────────────────────────────

def emit_card_claimed(*, board_id: str, card_id: str, profile_id: str) -> None:
    """Card moved Ready → Pending by this orchestrator."""
    _emit(
        "card_claimed",
        location_key=f"{board_id}/{card_id}",
        board_id=board_id,
        card_id=card_id,
        profile_id=profile_id,
    )


def emit_agent_started(*, board_id: str, card_id: str, profile_id: str, model_id: str) -> None:
    """BaseKanbanAgent about to start an iteration loop."""
    _emit(
        "agent_started",
        location_key=f"{board_id}/{card_id}",
        board_id=board_id,
        card_id=card_id,
        profile_id=profile_id,
        model_id=model_id,
    )


def emit_agent_finished(
    *,
    board_id: str,
    card_id: str,
    profile_id: str,
    destination: str,
    duration_seconds: Optional[float] = None,
) -> None:
    """Agent run completed cleanly; card landed in `destination` (In Review or Done)."""
    _emit(
        "agent_finished",
        location_key=f"{board_id}/{card_id}",
        board_id=board_id,
        card_id=card_id,
        profile_id=profile_id,
        destination=destination,
        duration_seconds=duration_seconds,
    )


def emit_agent_failed(
    *,
    board_id: str,
    card_id: str,
    profile_id: str,
    kind: str,
    detail: str = "",
) -> None:
    """Agent failed; card moved to Failed. `kind` is the AgentExecutionError kind
    (api_usage_limit / api_rate_limit / api_error / unknown)."""
    _emit(
        "agent_failed",
        location_key=f"{board_id}/{card_id}",
        board_id=board_id,
        card_id=card_id,
        profile_id=profile_id,
        kind=kind,
        detail=detail[:500],  # cap to keep ES doc size bounded
    )


def emit_card_blocked(*, board_id: str, card_id: str, profile_id: str, reason: str = "") -> None:
    """Card moved to Blocked because dependencies are unmet."""
    _emit(
        "card_blocked",
        location_key=f"{board_id}/{card_id}",
        board_id=board_id,
        card_id=card_id,
        profile_id=profile_id,
        reason=reason[:500],
    )


def emit_card_paused(*, board_id: str, card_id: str, profile_id: str, stateful: bool) -> None:
    """Agent asked the human a question; card stays in In Progress."""
    _emit(
        "card_paused",
        location_key=f"{board_id}/{card_id}",
        board_id=board_id,
        card_id=card_id,
        profile_id=profile_id,
        stateful=stateful,
    )
