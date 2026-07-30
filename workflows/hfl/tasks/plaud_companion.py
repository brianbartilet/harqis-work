"""Reconcile PLAUD recording state with tagged Google Calendar events.

The task is scheduled in fail-closed mode.  Unless
``PLAUD_COMPANION_ENABLED=true`` and the ADB serial/control token are present,
it returns without touching Google Calendar or the recorder.
"""
from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone
from typing import Any

from core.apps.es_logging.app.elasticsearch import log_result
from core.apps.sprout.app.celery import SPROUT
from core.utilities.logging.custom_logger import create_logger

from apps.google_apps.config import CONFIG as GOOGLE_CONFIG
from apps.google_apps.references.web.api.calendar import ApiServiceGoogleCalendarEvents
from apps.plaud.references.companion import PlaudCompanionController

_log = create_logger("hfl.plaud_companion")


def _truthy(value: str | None) -> bool:
    return (value or "").strip().lower() in {"1", "true", "yes", "on"}


def _event_bounds(event: dict[str, Any]) -> tuple[datetime | None, datetime | None]:
    start_raw = (event.get("start") or {}).get("dateTime")
    end_raw = (event.get("end") or {}).get("dateTime")
    if not start_raw or not end_raw:
        return None, None
    try:
        return datetime.fromisoformat(start_raw.replace("Z", "+00:00")), datetime.fromisoformat(
            end_raw.replace("Z", "+00:00")
        )
    except (TypeError, ValueError):
        return None, None


def active_recording_events(
    events: list[dict[str, Any]],
    *,
    now: datetime,
    event_tag: str,
) -> list[dict[str, Any]]:
    """Return timed, accepted events whose title/description contains the tag."""
    tag = event_tag.strip().lower()
    active: list[dict[str, Any]] = []
    for event in events:
        if event.get("status") == "cancelled":
            continue
        attendee_self = next(
            (a for a in event.get("attendees", []) if a.get("self")),
            {},
        )
        if attendee_self.get("responseStatus") == "declined":
            continue
        haystack = f"{event.get('summary', '')}\n{event.get('description', '')}".lower()
        if tag and tag not in haystack:
            continue
        start, end = _event_bounds(event)
        if start is None or end is None:
            continue
        local_now = now.astimezone(start.tzinfo) if start.tzinfo else now.replace(tzinfo=None)
        if start <= local_now < end:
            active.append(event)
    return active


def reconciliation_action(
    *,
    has_active_events: bool,
    status: dict[str, Any],
) -> str:
    """Choose how to acquire/release only the calendar recording claim."""
    if not status.get("success"):
        return "none"
    actual = status.get("state", "unknown")
    active_triggers = set(status.get("active_triggers") or [])
    if has_active_events and (
        "calendar" not in active_triggers or actual not in {"recording", "paused"}
    ):
        return "start"
    if not has_active_events and "calendar" in active_triggers:
        return "stop"
    return "none"


def _calendar_events(
    *,
    calendar_id: str,
    now: datetime,
    lookaround_minutes: int = 360,
) -> list[dict[str, Any]]:
    service = ApiServiceGoogleCalendarEvents(GOOGLE_CONFIG, calendar_id=calendar_id)
    response = service.list_events(
        time_min=(now - timedelta(minutes=lookaround_minutes)).isoformat(),
        time_max=(now + timedelta(minutes=lookaround_minutes)).isoformat(),
        max_results=100,
    )
    return response.get("items", []) if isinstance(response, dict) else []


@SPROUT.task()
@log_result()
def reconcile_plaud_companion(
    *,
    calendar_id: str | None = None,
    event_tag: str | None = None,
    dry_run: bool | None = None,
    now_iso: str | None = None,
) -> dict[str, Any]:
    """Match recorder state to active tagged calendar events.

    Overlapping events are treated as one continuous recording.  The task only
    stops a recording it is managing when no eligible event remains.
    """
    if not _truthy(os.environ.get("PLAUD_COMPANION_ENABLED")):
        return {"success": True, "skipped": "PLAUD_COMPANION_ENABLED is false"}

    controller = PlaudCompanionController()
    if not controller.ready:
        return {"success": False, "skipped": "companion ADB serial/token not configured"}

    calendar_id = calendar_id or os.environ.get("PLAUD_COMPANION_CALENDAR_ID", "primary")
    event_tag = event_tag or os.environ.get("PLAUD_COMPANION_EVENT_TAG", "#record")
    if dry_run is None:
        dry_run = _truthy(os.environ.get("PLAUD_COMPANION_DRY_RUN", "true"))
    now = (
        datetime.fromisoformat(now_iso.replace("Z", "+00:00"))
        if now_iso
        else datetime.now(timezone.utc)
    )

    try:
        events = _calendar_events(calendar_id=calendar_id, now=now)
        active = active_recording_events(events, now=now, event_tag=event_tag)
        status = controller.status()
        actual = status.get("state", "unknown")
        active_triggers = set(status.get("active_triggers") or [])
        desired = "recording" if active else "idle"
        action = reconciliation_action(
            has_active_events=bool(active),
            status=status,
        )

        base = {
            "success": bool(status.get("success")),
            "calendar_id": calendar_id,
            "event_tag": event_tag,
            "active_event_ids": [e.get("id") for e in active],
            "active_event_count": len(active),
            "actual_state": actual,
            "active_triggers": sorted(active_triggers),
            "desired_state": desired,
            "action": action,
            "dry_run": dry_run,
        }
        if not status.get("success"):
            return {
                **base,
                "action": "none",
                "error": status.get("error", "companion status unavailable"),
            }
        if action == "none" or dry_run:
            return base
        commanded = controller.command(action)
        return {**base, **commanded, "action": action, "dry_run": False}
    except Exception as exc:  # noqa: BLE001 - scheduled controller must not break beat
        _log.error("plaud companion reconciliation failed: %s", exc)
        return {"success": False, "error": str(exc), "dry_run": dry_run}
