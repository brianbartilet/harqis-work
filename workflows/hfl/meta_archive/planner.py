"""Create complete, review-pinned Meta thread-week work items."""

from __future__ import annotations

import hashlib
import json
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Iterable, Iterator

from workflows.hfl.meta_archive.models import MetaEvent, stable_hash
from workflows.hfl.meta_archive.parsers import (
    parse_facebook_posts, parse_facebook_thread, parse_instagram_html,
)


def content_sha256(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _json_bytes(payload: dict) -> bytes:
    return json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8")


def _write_json(path: Path, payload: dict) -> str:
    content = _json_bytes(payload)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_bytes(content)
    temporary.replace(path)
    return content_sha256(content)


def discover_export_roots(roots: Iterable[str], platform: str) -> list[Path]:
    prefix = f"{platform}-"
    found: dict[str, Path] = {}
    for raw in roots:
        root = Path(raw).expanduser().resolve()
        if not root.exists():
            continue
        candidates = [root] if root.name.startswith(prefix) else list(root.glob(f"{prefix}*"))
        for candidate in candidates:
            if candidate.is_dir():
                found[str(candidate).casefold()] = candidate
    return sorted(found.values(), key=lambda path: str(path).casefold())


def _record_parser_failure(failures: list[dict], *, platform: str,
                           export_root: Path, artifact: Path,
                           error: Exception) -> None:
    failures.append({
        "platform": platform,
        "artifact": f"meta-archive://{platform}/{export_root.name}/"
                    f"{artifact.relative_to(export_root).as_posix()}",
        "exception_category": type(error).__name__,
        "affected_artifacts": 1,
    })


def _iter_event_batches(platform: str, exports: list[Path],
                        failures: list[dict]) -> Iterator[list[MetaEvent]]:
    if platform == "facebook":
        for root in exports:
            for path in root.glob("your_facebook_activity/messages/**/message_*.json"):
                if path.name.startswith("._"):
                    continue
                try:
                    yield parse_facebook_thread(path, root)
                except (OSError, ValueError, TypeError, json.JSONDecodeError) as exc:
                    _record_parser_failure(
                        failures, platform=platform, export_root=root,
                        artifact=path, error=exc,
                    )
            for path in root.glob("your_facebook_activity/**/*post*.json"):
                if path.name.startswith("._"):
                    continue
                try:
                    yield parse_facebook_posts(path, root)
                except (OSError, ValueError, TypeError, json.JSONDecodeError) as exc:
                    _record_parser_failure(
                        failures, platform=platform, export_root=root,
                        artifact=path, error=exc,
                    )
    elif platform == "instagram":
        for root in exports:
            for path in root.glob("your_instagram_activity/messages/**/message_*.html"):
                if path.name.startswith("._"):
                    continue
                try:
                    yield parse_instagram_html(path, root, thread_id=path.parent.name)
                except (OSError, ValueError, TypeError) as exc:
                    _record_parser_failure(
                        failures, platform=platform, export_root=root,
                        artifact=path, error=exc,
                    )
            for path in root.glob("your_instagram_activity/media/*.html"):
                if path.name.startswith("._"):
                    continue
                if "post" in path.name.lower() or "stor" in path.name.lower():
                    try:
                        yield parse_instagram_html(
                            path, root, thread_id="authored-content", authored=True
                        )
                    except (OSError, ValueError, TypeError) as exc:
                        _record_parser_failure(
                            failures, platform=platform, export_root=root,
                            artifact=path, error=exc,
                        )
    else:
        raise ValueError("platform must be facebook or instagram")


def _initialize_staging(connection: sqlite3.Connection) -> None:
    connection.executescript("""
        PRAGMA journal_mode=WAL;
        CREATE TABLE events (
            event_id TEXT PRIMARY KEY,
            thread_id TEXT NOT NULL,
            week_start TEXT NOT NULL,
            occurred_at TEXT NOT NULL,
            payload TEXT NOT NULL
        );
        CREATE INDEX events_grouping ON events(week_start, thread_id, occurred_at, event_id);
        CREATE TABLE quarantine (
            event_id TEXT PRIMARY KEY,
            payload TEXT NOT NULL
        );
    """)


def build_import_plan(*, platform: str, archive_roots: list[str], work_dir: str,
                      max_events: int = 500_000,
                      future_tolerance_hours: int = 24) -> dict:
    """Build a complete plan without retaining the whole export in memory.

    ``max_events`` is an approval safety limit, not a truncation instruction.
    Preparation still obtains exact counts, but refuses to emit ``plan.json``
    when the number of valid unique events exceeds a positive limit.
    """
    exports = discover_export_roots(archive_roots, platform)
    if not exports:
        return {"ok": False, "reason": "no-export-roots", "platform": platform, "items": []}
    prepared_at = datetime.now(timezone.utc)
    run_id = f"{prepared_at:%Y%m%dT%H%M%S%fZ}-{stable_hash(platform, *(str(p) for p in exports))[:10]}"
    root = Path(work_dir).expanduser().resolve() / platform / run_id
    root.mkdir(parents=True, exist_ok=False)
    database = root / "staging.sqlite3"
    connection = sqlite3.connect(database)
    _initialize_staging(connection)
    parsed = duplicates = quarantined = 0
    parser_failures: list[dict] = []
    future_boundary = prepared_at + timedelta(hours=max(0, future_tolerance_hours))
    try:
        for batch in _iter_event_batches(platform, exports, parser_failures):
            for event in batch:
                parsed += 1
                if event.occurred_at_utc > future_boundary:
                    quarantine = {
                        "event_id": event.event_id,
                        "platform": event.platform,
                        "thread_id": event.thread_id,
                        "reason": "materially-future-timestamp",
                        "raw_timestamp": event.raw_timestamp,
                        "parsed_utc": event.occurred_at_utc.isoformat(),
                        "parsed_local": event.occurred_at_local.isoformat(),
                        "source_reference": event.source_reference or (event.references[0] if event.references else ""),
                    }
                    inserted = connection.execute(
                        "INSERT OR IGNORE INTO quarantine(event_id, payload) VALUES (?, ?)",
                        (event.event_id, json.dumps(quarantine, ensure_ascii=False)),
                    ).rowcount
                    quarantined += inserted
                    duplicates += int(not inserted)
                    continue
                local_date = event.occurred_at_local.date()
                week = local_date.fromordinal(local_date.toordinal() - local_date.weekday())
                inserted = connection.execute(
                    "INSERT OR IGNORE INTO events VALUES (?, ?, ?, ?, ?)",
                    (event.event_id, event.thread_id, week.isoformat(),
                     event.occurred_at_utc.isoformat(),
                     json.dumps(event.to_dict(), ensure_ascii=False)),
                ).rowcount
                duplicates += int(not inserted)
            connection.commit()
        valid = int(connection.execute("SELECT COUNT(*) FROM events").fetchone()[0])
        quarantine_rows = [
            json.loads(row[0]) for row in connection.execute(
                "SELECT payload FROM quarantine ORDER BY payload"
            )
        ]
        quarantine_path = root / "quarantine.json"
        quarantine_sha = _write_json(quarantine_path, {
            "schema_version": 2, "platform": platform,
            "prepared_at": prepared_at.isoformat(), "events": quarantine_rows,
        })
        parser_failures_path = root / "parser-failures.json"
        parser_failures_sha = _write_json(parser_failures_path, {
            "schema_version": 2, "platform": platform,
            "prepared_at": prepared_at.isoformat(), "failures": parser_failures,
        })
        counts = {
            "parsed": parsed, "valid_unique": valid, "duplicates": duplicates,
            "quarantined": quarantined, "parser_failures": len(parser_failures),
        }
        cap_reached = max_events > 0 and valid >= max_events
        if parser_failures or cap_reached:
            report = {
                "ok": False, "schema_version": 2, "complete": False,
                "truncated": cap_reached,
                "reason": ("parser-failures" if parser_failures
                           else "event-cap-reached"),
                "platform": platform, "run_id": run_id,
                "max_events": max_events, "counts": counts,
                "quarantine": {"path": str(quarantine_path), "sha256": quarantine_sha,
                               "count": quarantined},
                "parser_failures": {
                    "path": str(parser_failures_path),
                    "sha256": parser_failures_sha,
                    "count": len(parser_failures),
                },
            }
            report_path = root / "preparation-report.json"
            report_sha = _write_json(report_path, report)
            return {**report, "report_path": str(report_path), "report_sha256": report_sha}

        items: list[dict] = []
        groups = connection.execute(
            "SELECT thread_id, week_start, COUNT(*) FROM events "
            "GROUP BY thread_id, week_start ORDER BY week_start, thread_id"
        ).fetchall()
        for thread_id, week_start, event_count in groups:
            item_id = f"meta-{platform}-{stable_hash(platform, thread_id, week_start)[:24]}"
            events = [
                json.loads(row[0]) for row in connection.execute(
                    "SELECT payload FROM events WHERE thread_id=? AND week_start=? "
                    "ORDER BY occurred_at, event_id", (thread_id, week_start)
                )
            ]
            item_path = root / f"{item_id}.json"
            item_sha = _write_json(item_path, {
                "schema_version": 2, "item_id": item_id, "platform": platform,
                "thread_id": thread_id, "week_start": week_start, "events": events,
            })
            items.append({
                "id": item_id, "key": item_id, "path": str(item_path),
                "thread_id": thread_id, "week_start": week_start,
                "event_count": event_count, "sha256": item_sha,
            })
        preparation_report = {
            "ok": True, "schema_version": 2, "complete": True,
            "truncated": False, "platform": platform, "run_id": run_id,
            "prepared_at": prepared_at.isoformat(), "max_events": max_events,
            "counts": counts, "work_item_count": len(items),
            "quarantine": {"path": str(quarantine_path), "sha256": quarantine_sha,
                           "count": quarantined},
            "parser_failures": {
                "path": str(parser_failures_path), "sha256": parser_failures_sha,
                "count": 0,
            },
        }
        preparation_report_path = root / "preparation-report.json"
        preparation_report_sha = _write_json(
            preparation_report_path, preparation_report
        )
        manifest = {
            "ok": True, "schema_version": 2, "complete": True, "truncated": False,
            "platform": platform, "run_id": run_id, "prepared_at": prepared_at.isoformat(),
            "exports": [str(path) for path in exports], "max_events": max_events,
            "counts": counts, "events_discovered": valid,
            "work_item_count": len(items), "synthesis_eligible_items": len(items),
            "quarantine": {"path": str(quarantine_path), "sha256": quarantine_sha,
                           "count": quarantined},
            "parser_failures": {
                "path": str(parser_failures_path), "sha256": parser_failures_sha,
                "count": 0,
            },
            "preparation_report": {
                "path": str(preparation_report_path),
                "sha256": preparation_report_sha,
            },
            "items": items,
        }
        manifest_path = root / "plan.json"
        manifest_sha = _write_json(manifest_path, manifest)
        return {**manifest, "manifest_path": str(manifest_path),
                "manifest_sha256": manifest_sha}
    finally:
        connection.close()


def load_work_item(path: str, *, expected_sha256: str = "",
                   allowed_root: str = "") -> tuple[dict, list[MetaEvent]]:
    resolved = Path(path).expanduser().resolve(strict=True)
    if allowed_root:
        root = Path(allowed_root).expanduser().resolve(strict=True)
        if not resolved.is_relative_to(root):
            raise ValueError("work item is outside the approved manifest directory")
    content = resolved.read_bytes()
    if expected_sha256:
        expected = expected_sha256.strip().casefold()
        if len(expected) != 64 or content_sha256(content) != expected:
            raise ValueError("work item integrity check failed")
    payload = json.loads(content.decode("utf-8"))
    return payload, [MetaEvent.from_dict(item) for item in payload.get("events") or []]
