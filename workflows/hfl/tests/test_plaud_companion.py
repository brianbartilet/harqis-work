from datetime import datetime, timezone

from workflows.hfl.tasks.plaud_companion import (
    active_recording_events,
    reconciliation_action,
)


def _event(
    *,
    summary="Customer call #record",
    start="2026-07-31T10:00:00+08:00",
    end="2026-07-31T11:00:00+08:00",
    **extra,
):
    return {
        "id": "evt-1",
        "summary": summary,
        "start": {"dateTime": start},
        "end": {"dateTime": end},
        **extra,
    }


def test_active_recording_events_matches_tag_and_timezone():
    now = datetime(2026, 7, 31, 2, 30, tzinfo=timezone.utc)
    result = active_recording_events([_event()], now=now, event_tag="#record")
    assert [event["id"] for event in result] == ["evt-1"]


def test_active_recording_events_excludes_all_day_cancelled_and_declined():
    now = datetime(2026, 7, 31, 2, 30, tzinfo=timezone.utc)
    events = [
        {"id": "all-day", "summary": "#record", "start": {"date": "2026-07-31"}, "end": {"date": "2026-08-01"}},
        _event(status="cancelled"),
        _event(attendees=[{"self": True, "responseStatus": "declined"}]),
    ]
    assert active_recording_events(events, now=now, event_tag="#record") == []


def test_active_recording_events_requires_explicit_tag():
    now = datetime(2026, 7, 31, 2, 30, tzinfo=timezone.utc)
    assert active_recording_events(
        [_event(summary="Private appointment")],
        now=now,
        event_tag="#record",
    ) == []


def test_reconciliation_acquires_missing_calendar_claim():
    assert reconciliation_action(
        has_active_events=True,
        status={"success": True, "state": "recording", "active_triggers": ["location"]},
    ) == "start"


def test_reconciliation_releases_only_owned_calendar_claim():
    assert reconciliation_action(
        has_active_events=False,
        status={
            "success": True,
            "state": "recording",
            "active_triggers": ["calendar", "location"],
        },
    ) == "stop"
    assert reconciliation_action(
        has_active_events=False,
        status={"success": True, "state": "recording", "active_triggers": ["location"]},
    ) == "none"


def test_reconciliation_never_commands_when_status_failed():
    assert reconciliation_action(
        has_active_events=True,
        status={"success": False, "error": "ADB unavailable"},
    ) == "none"
