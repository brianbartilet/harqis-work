import json
import os
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from workflows.hud.collectors.hermes_pushes import (
    DEFAULT_WINDOW_HOURS,
    EMPTY_STATE,
    RECENT_HEADING,
    STALE_STATE,
    UNAVAILABLE_STATE,
    _extract_delivered_cron_text,
    build_snapshot,
    collect_cron_pushes,
    collect_interactive_pushes,
    compose_hermes_radar,
    displayed_item_count,
    export_snapshot,
    load_snapshot,
    sanitize_message,
    sanitize_preview,
)


def _create_state_db(path: Path, messages: list[tuple[str, str, str]]) -> None:
    connection = sqlite3.connect(path)
    connection.executescript(
        """
        CREATE TABLE sessions (id TEXT PRIMARY KEY, source TEXT);
        CREATE TABLE messages (
            id INTEGER PRIMARY KEY,
            session_id TEXT,
            role TEXT,
            content TEXT,
            timestamp TEXT
        );
        INSERT INTO sessions VALUES ('telegram-session', 'telegram');
        INSERT INTO sessions VALUES ('cli-session', 'cli');
        """
    )
    for session_id, role, content_timestamp in messages:
        content, timestamp = content_timestamp.split("|", 1)
        connection.execute(
            "INSERT INTO messages(session_id, role, content, timestamp) VALUES (?, ?, ?, ?)",
            (session_id, role, content, timestamp),
        )
    connection.commit()
    connection.close()


def test_sanitize_message_removes_secrets_unicode_and_preserves_lines():
    text = (
        "**Done** \U0001f680 caf\u00e9\n\n- First item\n- Second item\n"
        "token=abc123 /Users/example/private.txt "
        "chat_id=-123456 job_id=internal-42 "
        "request_id=123e4567-e89b-42d3-a456-426614174000 "
        "unlabelled=123456789012 MEDIA:/tmp/report.png Bearer very-secret-token"
    )
    message = sanitize_message(text)
    assert "abc123" not in message
    assert "123456" not in message
    assert "internal-42" not in message
    assert "123e4567" not in message
    assert "123456789012" not in message
    assert "/Users" not in message
    assert "/tmp" not in message
    assert "very-secret-token" not in message
    assert "**" not in message
    assert "[REDACTED]" in message
    assert "\U0001f680" not in message
    assert "cafe" in message
    assert "\n\n- First item\n- Second item" in message
    assert message.isascii()
    assert sanitize_preview(text).isascii()


def test_collect_interactive_pushes_only_exports_recent_assistant_telegram(tmp_path):
    now = datetime(2026, 7, 14, 12, tzinfo=timezone.utc)
    db = tmp_path / "state.db"
    _create_state_db(
        db,
        [
            ("telegram-session", "assistant", f"Recent reply|{(now - timedelta(minutes=5)).timestamp()}"),
            ("telegram-session", "user", f"Private user input|{(now - timedelta(minutes=4)).isoformat()}"),
            ("cli-session", "assistant", f"CLI reply|{(now - timedelta(minutes=3)).isoformat()}"),
            ("telegram-session", "assistant", f"Old reply|{(now - timedelta(hours=9)).isoformat()}"),
            ("telegram-session", "assistant", f"HERMES RADAR dump loop|{(now - timedelta(minutes=2)).isoformat()}"),
        ],
    )

    items = collect_interactive_pushes(db, since=now - timedelta(hours=8), now=now)

    assert [item["text"] for item in items] == ["Recent reply"]
    assert items[0]["kind"] == "interactive"


def test_collect_cron_pushes_uses_only_telegram_jobs_and_reports_failure(tmp_path):
    now = datetime(2026, 7, 14, 12, tzinfo=timezone.utc)
    jobs_path = tmp_path / "jobs.json"
    output = tmp_path / "output"
    delivered_dir = output / "telegram-job"
    local_dir = output / "local-job"
    loop_dir = output / "loop-job"
    for directory in (delivered_dir, local_dir, loop_dir):
        directory.mkdir(parents=True)

    jobs_path.write_text(
        json.dumps(
            {
                "jobs": [
                    {
                        "id": "telegram-job",
                        "name": "Daily status",
                        "deliver": "telegram:configured",
                        "last_run_at": now.isoformat(),
                        "last_status": "ok",
                        "last_delivery_error": "gateway unavailable",
                    },
                    {"id": "local-job", "name": "Local only", "deliver": "local"},
                    {
                        "id": "loop-job",
                        "name": "daily-radar-dump-to-telegram",
                        "deliver": "telegram:configured",
                    },
                ]
            }
        ),
        encoding="utf-8",
    )
    delivered = delivered_dir / "run.md"
    delivered.write_text("This output should be replaced by the delivery failure", encoding="utf-8")
    local = local_dir / "run.md"
    local.write_text("Never export this", encoding="utf-8")
    loop = loop_dir / "run.md"
    loop.write_text("Looped radar dump", encoding="utf-8")
    timestamp = now.timestamp()
    for path in (delivered, local, loop):
        os.utime(path, (timestamp, timestamp))

    items = collect_cron_pushes(
        jobs_path, output, since=now - timedelta(hours=8), now=now
    )

    assert len(items) == 1
    assert items[0]["source"] == "Daily status"
    assert items[0]["status"] == "delivery_failed"
    assert "Delivery failed" in items[0]["text"]
    assert "gateway unavailable" in items[0]["text"]


def test_cron_audit_parser_exports_response_only_and_fails_closed():
    audit = """# Cron Job: status

**Job ID:** private-id

## Prompt

Never expose this prompt token=private-value

## Response
This heading is part of the prompt example and must stay private.

## Response

Safe delivered update
"""
    assert _extract_delivered_cron_text(audit) == "Safe delivered update"
    assert (
        _extract_delivered_cron_text(
            "# Cron Job: unknown\n\n**Job ID:** private-id\n"
        )
        is None
    )


def test_build_snapshot_exports_scheduled_deliveries_and_excludes_conversation(tmp_path):
    now = datetime(2026, 7, 14, 12, tzinfo=timezone.utc)
    home = tmp_path / "hermes"
    output = home / "cron" / "output" / "scheduled-job"
    output.mkdir(parents=True)
    _create_state_db(
        home / "state.db",
        [
            ("telegram-session", "assistant", f"Conversational reply|{(now - timedelta(minutes=1)).isoformat()}"),
            ("telegram-session", "user", f"Private user input|{(now - timedelta(minutes=2)).isoformat()}"),
        ],
    )
    (home / "cron" / "jobs.json").write_text(
        json.dumps(
            {
                "jobs": [
                    {
                        "id": "scheduled-job",
                        "name": "Scheduled status",
                        "deliver": "telegram:configured",
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    newest = output / "newest.md"
    older = output / "older.md"
    newest.write_text("Duplicate scheduled update", encoding="utf-8")
    older.write_text("Duplicate scheduled update", encoding="utf-8")
    os.utime(newest, ((now - timedelta(minutes=1)).timestamp(),) * 2)
    os.utime(older, ((now - timedelta(minutes=2)).timestamp(),) * 2)

    snapshot = build_snapshot(hermes_home=home, now=now, max_items=0)

    assert snapshot["schema_version"] == 2
    assert snapshot["window_hours"] == DEFAULT_WINDOW_HOURS
    assert [item["text"] for item in snapshot["items"]] == [
        "Duplicate scheduled update",
        "Duplicate scheduled update",
    ]
    assert "Conversational reply" not in json.dumps(snapshot)
    assert "Private user input" not in json.dumps(snapshot)
    assert {item["kind"] for item in snapshot["items"]} == {"scheduled"}


def test_export_failure_preserves_last_valid_snapshot(tmp_path):
    destination = tmp_path / "hermes-radar.json"
    destination.write_text('{"last": "valid"}', encoding="utf-8")

    with pytest.raises(OSError):
        export_snapshot(snapshot_path=destination, hermes_home=tmp_path / "missing")

    assert destination.read_text(encoding="utf-8") == '{"last": "valid"}'


def test_load_snapshot_marks_stale_and_unavailable_does_not_preserve_old_messages(tmp_path):
    now = datetime(2026, 7, 14, 12, tzinfo=timezone.utc)
    snapshot_path = tmp_path / "hermes-radar.json"
    snapshot_path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "generated_at": (now - timedelta(hours=2)).isoformat(),
                "window_hours": 8,
                "max_items": 10,
                "items": [
                    {
                        "timestamp": (now - timedelta(minutes=5)).isoformat(),
                        "source": "Scheduled update",
                        "kind": "scheduled",
                        "status": "delivered",
                        "preview": "Useful update",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    stale = load_snapshot(snapshot_path, now=now)
    rendered = compose_hermes_radar(stale)
    assert stale["state"] == "stale"
    assert stale["schema_version"] == 2
    assert RECENT_HEADING in rendered
    assert "Useful update" in rendered
    assert STALE_STATE in rendered

    unavailable = load_snapshot(tmp_path / "missing.json", now=now)
    unavailable_rendered = compose_hermes_radar(unavailable)
    assert "Useful update" not in unavailable_rendered
    assert UNAVAILABLE_STATE in unavailable_rendered


def test_empty_snapshot_has_explicit_empty_state():
    rendered = compose_hermes_radar({"state": "fresh", "items": []})
    assert EMPTY_STATE in rendered


def test_load_snapshot_enforces_twelve_hour_cutoff_at_render_time(tmp_path):
    now = datetime(2026, 7, 14, 12, tzinfo=timezone.utc)
    snapshot_path = tmp_path / "hermes-radar.json"
    snapshot_path.write_text(
        json.dumps(
            {
                "schema_version": 2,
                "generated_at": now.isoformat(),
                "window_hours": 8,
                "max_items": 0,
                "items": [
                    {
                        "timestamp": (now - timedelta(hours=11, minutes=59)).isoformat(),
                        "source": "Scheduled update",
                        "kind": "scheduled",
                        "status": "delivered",
                        "text": "Inside window",
                    },
                    {
                        "timestamp": (now - timedelta(hours=12, minutes=1)).isoformat(),
                        "source": "Scheduled update",
                        "kind": "scheduled",
                        "status": "delivered",
                        "text": "Outside window",
                    },
                ],
            }
        ),
        encoding="utf-8",
    )

    loaded = load_snapshot(snapshot_path, now=now)

    assert [item["text"] for item in loaded["items"]] == ["Inside window"]
    assert loaded["window_hours"] == 12


def test_radar_renders_delivered_scheduled_messages_only():
    snapshot = {
        "state": "fresh",
        "items": [
            {
                "timestamp": "2026-07-14T12:00:00+00:00",
                "source": "Scheduled report",
                "kind": "scheduled",
                "status": "delivered",
                "text": "Report line\n\n- detail",
            },
            {
                "timestamp": "2026-07-14T11:59:00+00:00",
                "source": "Hermes chat",
                "kind": "interactive",
                "status": "delivered",
                "text": "Conversational reply",
            },
            {
                "timestamp": "2026-07-14T11:58:00+00:00",
                "source": "Failed job",
                "kind": "scheduled",
                "status": "delivery_failed",
                "text": "Not received in Telegram",
            },
        ],
    }

    rendered = compose_hermes_radar(snapshot)

    assert "Scheduled report\nReport line\n\n- detail" in rendered
    assert "Conversational reply" not in rendered
    assert "Not received in Telegram" not in rendered
    assert displayed_item_count(snapshot) == 1


def test_hermes_radar_schedules_keep_fast_path_model_free():
    from workflows.hud.tasks_config import WORKFLOWS_HUD

    deep = WORKFLOWS_HUD["run-job--show_daily_radar"]
    exporter = WORKFLOWS_HUD["run-job--export_hermes_radar_snapshot"]
    refresh = WORKFLOWS_HUD["run-job--refresh_hermes_radar"]

    assert set(deep["schedule"].hour) == {8, 12, 16, 20}
    assert set(exporter["schedule"].minute) == {0}
    assert set(refresh["schedule"].minute) == {5}
    assert exporter["kwargs"]["window_hours"] == 12
    assert exporter["kwargs"]["max_items"] == 0
    assert "model" not in exporter["kwargs"]
    assert "model" not in refresh["kwargs"]
    assert deep["manifesto"]["express_target"] == "rainmeter:HERMES_RADAR"
