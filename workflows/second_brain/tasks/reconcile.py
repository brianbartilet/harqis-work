"""Durable reconciliation and read-only source collection for Second Brain."""

from __future__ import annotations

import importlib
import uuid
from typing import Any

from core.apps.es_logging.app.elasticsearch import log_result
from core.apps.sprout.app.celery import SPROUT

from workflows.second_brain.events import publish_feed_change
from workflows.second_brain.models import FeedItem, isoformat
from workflows.second_brain.registry import configured_bindings, selected_operations
from workflows.second_brain.resolver import resolve_modes
from workflows.second_brain.store import get_store


def _load_callable(path: str):
    module_name, _, attribute = path.rpartition(".")
    if not module_name or not attribute:
        raise ValueError("invalid registered collector path")
    return getattr(importlib.import_module(module_name), attribute)


def _current_calendar_signal() -> dict[str, Any] | None:
    try:
        from apps.apps_config import CONFIG_MANAGER
        from apps.google_apps.references.web.api.calendar import ApiServiceGoogleCalendarEvents, EventType

        events = ApiServiceGoogleCalendarEvents(CONFIG_MANAGER.get("GOOGLE_APPS")).get_all_events_today(EventType.NOW)
        summaries = sorted({str(event.get("calendarSummary") or "") for event in events if event.get("calendarSummary")})
        return {"event_type": "calendar", "payload": {"calendar_categories": summaries}}
    except Exception:
        return None


def reconcile(*, store=None, correlation_id: str | None = None, task_id: str = "", force: bool = False) -> dict[str, Any]:
    """Resolve active modes and materialize all allowlisted advisory operations."""
    canonical = store or get_store()
    correlation = correlation_id or str(uuid.uuid4())
    config = canonical.get_config()
    signals = canonical.recent_context(limit=50)
    calendar_signal = _current_calendar_signal()
    if calendar_signal:
        signals.insert(0, calendar_signal)
    agent_candidate = None
    agent_state = "disabled"
    if config.get("hermes_enabled"):
        try:
            from workflows.second_brain.hermes import interpret_context

            agent_candidate = interpret_context(signals, config.get("modes") or [])
            agent_state = "available"
        except Exception:
            agent_state = "degraded"
    decision = resolve_modes(
        signals,
        mode_definitions=config.get("modes") or [],
        manual_override=canonical.active_override(),
        agent_candidate=agent_candidate,
        correlation_id=correlation,
    )
    canonical.record_decision(decision)
    retired_payloads = canonical.retire_feed_items(configured_bindings(config.get("modes") or []))
    for payload in retired_payloads:
        publish_feed_change(payload)
    changed = len(retired_payloads)
    changed_payloads: list[dict[str, Any]] = list(retired_payloads)
    unchanged = 0
    failures: list[dict[str, str]] = []
    operation_results: list[dict[str, Any]] = []
    mode_by_id = {mode["mode_id"]: mode for mode in config.get("modes") or []}
    for operation, categories, refresh_minutes in selected_operations(decision.effective_modes, config.get("modes") or []):
        if not force and not canonical.operation_due(operation.operation_id, refresh_minutes):
            operation_results.append({"operation_id": operation.operation_id, "state": "fresh", "changed": 0})
            continue
        run_id = f"run-{uuid.uuid4().hex}"
        canonical.start_run(
            run_id=run_id,
            operation_id=operation.operation_id,
            correlation_id=correlation,
            task_id=task_id,
        )
        try:
            collector = _load_callable(operation.collector)
            items = collector(correlation_id=correlation, **operation.kwargs)
            operation_changed = 0
            for item in items:
                if not isinstance(item, FeedItem):
                    raise TypeError(f"{operation.operation_id} returned a non-FeedItem")
                for category in categories:
                    eligible_clients = tuple(mode_by_id.get(category, {}).get("client_eligibility") or ("web",))
                    projected = FeedItem(
                        **{
                            **item.__dict__,
                            "logical_key": f"{category}:{operation.operation_id}:{item.logical_key}",
                            "category": category,
                            "allowed_clients": tuple(client for client in item.allowed_clients if client in eligible_clients),
                            "run_id": run_id,
                            "operation_id": operation.operation_id,
                            "item_id": "",
                        }
                    )
                    payload, was_changed = canonical.upsert_feed_item(projected)
                    if was_changed:
                        changed += 1
                        operation_changed += 1
                        changed_payloads.append(payload)
                        publish_feed_change(payload)
                    else:
                        unchanged += 1
            result = {"items": len(items), "changed": operation_changed}
            canonical.finish_run(run_id=run_id, state="success", result=result)
            operation_results.append({"operation_id": operation.operation_id, **result})
        except Exception as exc:
            error = {"operation_id": operation.operation_id, "error_type": type(exc).__name__}
            failures.append(error)
            canonical.finish_run(run_id=run_id, state="failure", result=error, error_type=type(exc).__name__)
            from datetime import datetime, timedelta, timezone

            failure_category = categories[0] if categories else "default"
            category_clients = mode_by_id.get(failure_category, {}).get("client_eligibility") or ("web",)
            failure_item = FeedItem(
                logical_key=f"source-error:{operation.operation_id}",
                category=failure_category,
                kind="source_error",
                title=f"{operation.operation_id} is temporarily unavailable",
                summary=f"Collection failed with {type(exc).__name__}; other sources continue.",
                priority=72,
                confidence=1.0,
                status="degraded",
                source_refs=(operation.operation_id,),
                fresh_until=isoformat(datetime.now(timezone.utc) + timedelta(minutes=5)),
                expires_at=isoformat(datetime.now(timezone.utc) + timedelta(minutes=30)),
                allowed_clients=tuple(client for client in ("web", "cli", "rainmeter") if client in category_clients),
                reason_codes=("collector-failure",),
                correlation_id=correlation,
                run_id=run_id,
                operation_id=operation.operation_id,
            )
            payload, was_changed = canonical.upsert_feed_item(failure_item)
            if was_changed:
                changed += 1
                changed_payloads.append(payload)
                publish_feed_change(payload)
    deliveries: list[str] = []
    if changed_payloads:
        clients = config.get("clients") or {}
        if clients.get("telegram"):
            from workflows.queues import WorkflowQueue

            result = SPROUT.send_task(
                "workflows.second_brain.tasks.deliver.deliver_second_brain_telegram",
                queue=WorkflowQueue.HOST.value,
            )
            deliveries.append(str(result.id))
        if clients.get("rainmeter"):
            from workflows.queues import WorkflowQueue

            result = SPROUT.send_task(
                "workflows.hud.tasks.second_brain.render_second_brain_rainmeter",
                queue=WorkflowQueue.HUD.value,
            )
            deliveries.append(str(result.id))
    return {
        "text": "Second Brain reconciliation completed",
        "correlation_id": correlation,
        "effective_modes": list(decision.effective_modes),
        "decision_id": decision.decision_id,
        "agent_state": agent_state,
        "changed": changed,
        "retired": len(retired_payloads),
        "unchanged": unchanged,
        "failures": failures,
        "operations": operation_results,
        "delivery_task_ids": deliveries,
    }


@SPROUT.task()
@log_result()
def reconcile_second_brain(**kwargs):
    request = getattr(reconcile_second_brain, "request", None)
    return reconcile(
        correlation_id=kwargs.get("correlation_id"),
        task_id=str(getattr(request, "id", "") or ""),
        force=bool(kwargs.get("force", False)),
    )
