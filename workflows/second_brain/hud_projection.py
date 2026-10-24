"""Read-only bridge from legacy HUD results into portable Second Brain items.

HUD tasks retain collection with optional legacy Rainmeter rendering. After a successful run the
``capture_hud_projection`` decorator writes a bounded, redacted copy of the
returned payload to Elasticsearch.  Second Brain operations only read that
projection; they never import or execute Windows/Rainmeter task modules.
"""

from __future__ import annotations

import functools
import json
import re
from collections.abc import Mapping
from datetime import datetime, timedelta, timezone
from typing import Any, Callable
from urllib.parse import urlparse

from core.utilities.logging.custom_logger import logger as log

from workflows.second_brain.models import FeedItem, isoformat


HUD_PROJECTION_INDEX = "harqis-second-brain-hud"
_MAX_PROJECTION_BYTES = 64 * 1024
_MAX_TEXT_CHARS = 12_000
_SENSITIVE_KEYS = frozenset(
    {
        "access_token",
        "api_key",
        "authorization",
        "cookie",
        "credentials",
        "password",
        "refresh_token",
        "secret",
        "token",
    }
)
_ANSI_ESCAPE = re.compile(r"\x1b(?:\[[0-?]*[ -/]*[@-~]|\][^\x07]*(?:\x07|\x1b\\))")
_CONTROL_CHARS = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
_SECRET_ASSIGNMENT = re.compile(
    r"(?i)\b(access[_ -]?token|api[_ -]?key|authorization|bearer|cookie|credentials|password|"
    r"refresh[_ -]?token|secret|token)(\s*[:=]\s*|\s+)((?:bearer\s+)?[^\s,;]+)"
)
_TOKEN_SHAPE = re.compile(r"\b(?:sk|ghp|github_pat|xox[baprs])[-_][A-Za-z0-9_-]{12,}\b")
_LONG_NUMBER = re.compile(r"(?<!\d)\d{8,}(?!\d)")


def _clean_text(value: Any, *, limit: int = _MAX_TEXT_CHARS) -> str:
    text = _ANSI_ESCAPE.sub("", str(value or ""))
    text = _CONTROL_CHARS.sub("", text).replace("\r\n", "\n").replace("\r", "\n")
    text = _SECRET_ASSIGNMENT.sub(lambda match: f"{match.group(1)}{match.group(2)}[redacted]", text)
    text = _TOKEN_SHAPE.sub("[redacted-token]", text)
    text = _LONG_NUMBER.sub(lambda match: f"••••{match.group(0)[-4:]}", text)
    return text.strip()[:limit]


def _safe_value(value: Any, *, key: str = "", depth: int = 0) -> Any:
    normalized_key = key.strip().casefold().replace("-", "_")
    if any(part in normalized_key for part in _SENSITIVE_KEYS):
        return "[redacted]"
    if depth >= 6:
        return _clean_text(value, limit=500)
    if value is None or isinstance(value, (bool, float)):
        return value
    if isinstance(value, int):
        return _clean_text(value) if abs(value) >= 10_000_000 else value
    if isinstance(value, str):
        return _clean_text(value)
    if isinstance(value, Mapping):
        return {
            _clean_text(child_key, limit=120): _safe_value(child, key=str(child_key), depth=depth + 1)
            for child_key, child in list(value.items())[:100]
        }
    if isinstance(value, (list, tuple, set)):
        return [_safe_value(child, depth=depth + 1) for child in list(value)[:100]]
    return _clean_text(value, limit=1_000)


def _bounded_payload(result: Any) -> dict[str, Any]:
    payload = _safe_value(result if isinstance(result, Mapping) else {"text": result})
    encoded = json.dumps(payload, ensure_ascii=False, default=str).encode("utf-8")
    if len(encoded) <= _MAX_PROJECTION_BYTES:
        return payload
    return {
        "text": _clean_text(payload.get("text", ""), limit=24_000),
        "summary": _clean_text(payload.get("summary", ""), limit=1_000),
        "projection_truncated": True,
    }


def _publish_projection(source_task: str, result: Any) -> None:
    from core.apps.es_logging.app.elasticsearch import post

    post(
        json_dump={
            "source_task": source_task,
            "captured_at": isoformat(),
            "payload": _bounded_payload(result),
        },
        index_name=HUD_PROJECTION_INDEX,
        location_key=source_task,
        use_interval_map=False,
    )


def _should_capture_projection() -> bool:
    """Only worker-dispatched executions publish; direct calls stay side-effect free."""
    try:
        from celery import current_task

        request = getattr(current_task, "request", None)
        return bool(
            request is not None
            and getattr(request, "id", None)
            and not getattr(request, "called_directly", True)
        )
    except Exception:
        return False


def capture_hud_projection(*, source_task: str | None = None) -> Callable:
    """Publish a successful HUD return value without affecting HUD execution."""

    def decorator(func: Callable) -> Callable:
        source = source_task or f"{func.__module__}.{func.__qualname__}"

        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            result = func(*args, **kwargs)
            if isinstance(result, Mapping) and result.get('skipped'):
                return result
            if not _should_capture_projection():
                return result
            try:
                _publish_projection(source, result)
            except Exception as exc:
                log.warning(
                    "Second Brain HUD projection skipped for %s (%s)",
                    source,
                    type(exc).__name__,
                )
            return result

        return wrapper

    return decorator


def _projection_source(raw: Any) -> dict[str, Any]:
    if isinstance(raw, Mapping):
        source = raw.get("_source")
        return dict(source) if isinstance(source, Mapping) else dict(raw)
    getter = getattr(raw, "get_dict", None)
    if callable(getter):
        return dict(getter())
    return dict(getattr(raw, "__dict__", {}) or {})


def _load_projection(source_task: str) -> dict[str, Any] | None:
    from core.apps.es_logging.app.elasticsearch import get_index_data

    matches = [
        _projection_source(raw)
        for raw in get_index_data(HUD_PROJECTION_INDEX, fetch_docs=250)
    ]
    matches = [item for item in matches if item.get("source_task") == source_task]
    return max(matches, key=lambda item: str(item.get("captured_at") or item.get("date") or ""), default=None)


def _parse_datetime(value: Any) -> datetime | None:
    raw = str(value or "").strip()
    if not raw:
        return None
    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        return parsed.replace(tzinfo=parsed.tzinfo or timezone.utc).astimezone(timezone.utc)
    except ValueError:
        return None


def _safe_links(value: Any) -> dict[str, str]:
    if not isinstance(value, Mapping):
        return {}
    links: dict[str, str] = {}
    for key, raw in list(value.items())[:12]:
        url = str(raw or "").strip()
        parsed = urlparse(url)
        if parsed.scheme in {"http", "https"} and parsed.netloc:
            links[str(key)[:40]] = url[:2_000]
    return links


def _summary(payload: dict[str, Any], text: str) -> str:
    summary = payload.get("summary")
    if isinstance(summary, str) and summary.strip():
        return _clean_text(summary, limit=360)
    if isinstance(summary, Mapping):
        return " · ".join(
            f"{key}: {_clean_text(value, limit=80)}"
            for key, value in list(summary.items())[:4]
        )[:360]
    first_line = next((line.strip() for line in text.splitlines() if line.strip()), "")
    return first_line[:360] or "HUD task completed without a textual summary."


_UNSET = object()


def collect_hud_projection(
    *,
    source_task: str,
    operation_id: str,
    label: str,
    correlation_id: str,
    stale_after_minutes: int = 60,
    priority: int = 55,
    sensitivity: str = "internal",
    projection: Any = _UNSET,
) -> list[FeedItem]:
    """Normalize the latest captured HUD result into one advisory feed item."""
    if projection is _UNSET:
        projection = _load_projection(source_task)
    now = datetime.now(timezone.utc)
    stale_after = max(5, min(10_080, int(stale_after_minutes)))
    allowed_clients = ("web", "telegram", "rainmeter", "cli")
    if projection is None:
        return [
            FeedItem(
                logical_key=f"hud-projection:{operation_id}",
                category="default",
                kind="hud_projection",
                title=f"{label} is awaiting its first capture",
                summary="Run the source HUD task once; Second Brain will ingest later results automatically.",
                priority=max(20, int(priority) - 25),
                confidence=1.0,
                status="awaiting_source",
                source_refs=(source_task,),
                fresh_until=isoformat(now + timedelta(minutes=5)),
                expires_at=isoformat(now + timedelta(days=7)),
                sensitivity=sensitivity,
                allowed_clients=("web", "cli", "rainmeter"),
                reason_codes=("hud-projection-missing",),
                correlation_id=correlation_id,
            )
        ]

    payload = projection.get("payload") if isinstance(projection.get("payload"), Mapping) else {}
    text = _clean_text(payload.get("text") or payload.get("feed_text") or "")
    captured_raw = projection.get("captured_at") or projection.get("date")
    captured_at = _parse_datetime(captured_raw)
    stale = captured_at is None or (now - captured_at).total_seconds() > stale_after * 60
    details = text
    metrics = payload.get("metrics")
    if isinstance(metrics, Mapping) and metrics:
        metrics_text = json.dumps(_safe_value(metrics), indent=2, ensure_ascii=False, default=str)
        details = f"{details}\n\nMetrics\n```json\n{metrics_text[:4_000]}\n```".strip()
    return [
        FeedItem(
            logical_key=f"hud-projection:{operation_id}",
            category="default",
            kind="hud_projection",
            title=label,
            summary=_summary(payload, text),
            details=details[:12_000],
            priority=max(0, int(priority) - (12 if stale else 0)),
            confidence=1.0,
            status="stale" if stale else "fresh",
            source_refs=(source_task,),
            source_at=isoformat(captured_at) if captured_at else str(captured_raw or ""),
            fresh_until=isoformat((captured_at or now) + timedelta(minutes=stale_after)),
            expires_at=isoformat(now + timedelta(days=7)),
            sensitivity=sensitivity,
            allowed_clients=allowed_clients,
            links=_safe_links(payload.get("links")),
            reason_codes=(("hud-projection-stale",) if stale else ("hud-projection-fresh",)),
            correlation_id=correlation_id,
        )
    ]
