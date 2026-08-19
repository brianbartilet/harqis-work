"""Durable dispatch state for reviewed Meta archive manifests."""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


TERMINAL_STATES = {"succeeded", "distilled-skip", "failed"}


def _connect(path: str | Path) -> sqlite3.Connection:
    connection = sqlite3.connect(str(path), timeout=30)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA journal_mode=WAL")
    return connection


def initialize_checkpoint(path: str | Path, *, manifest_sha256: str,
                          platform: str, items: list[dict[str, Any]],
                          allow_cloud: bool, synthesize: bool) -> None:
    with _connect(path) as connection:
        connection.executescript("""
            CREATE TABLE IF NOT EXISTS metadata (key TEXT PRIMARY KEY, value TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS items (
                item_id TEXT PRIMARY KEY,
                work_item_sha256 TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'planned',
                task_id TEXT NOT NULL DEFAULT '',
                attempts INTEGER NOT NULL DEFAULT 0,
                error TEXT NOT NULL DEFAULT '',
                result_json TEXT NOT NULL DEFAULT '',
                updated_at TEXT NOT NULL
            );
        """)
        expected = {
            "manifest_sha256": manifest_sha256, "platform": platform,
            "allow_cloud": json.dumps(bool(allow_cloud)),
            "synthesize": json.dumps(bool(synthesize)),
        }
        existing = dict(connection.execute("SELECT key, value FROM metadata").fetchall())
        if existing and any(existing.get(key) != value for key, value in expected.items()):
            raise ValueError("dispatch checkpoint is pinned to different manifest or privacy policies")
        connection.executemany(
            "INSERT OR IGNORE INTO metadata(key, value) VALUES (?, ?)", expected.items()
        )
        now = datetime.now(timezone.utc).isoformat()
        connection.executemany(
            "INSERT OR IGNORE INTO items(item_id, work_item_sha256, updated_at) VALUES (?, ?, ?)",
            [(str(item["id"]), str(item["sha256"]), now) for item in items],
        )
        rows = dict(connection.execute("SELECT item_id, work_item_sha256 FROM items").fetchall())
        if len(rows) != len(items) or any(rows.get(str(item["id"])) != str(item["sha256"])
                                          for item in items):
            raise ValueError("dispatch checkpoint items differ from the approved manifest")


def reserve_items(path: str | Path, *, max_items: int,
                  item_ids: list[str] | None = None,
                  retry_failed: bool = False) -> list[str]:
    allowed = ["planned"] + (["failed"] if retry_failed else [])
    with _connect(path) as connection:
        connection.execute("BEGIN IMMEDIATE")
        placeholders = ",".join("?" for _ in allowed)
        parameters: list[Any] = list(allowed)
        query = f"SELECT item_id FROM items WHERE status IN ({placeholders})"
        if item_ids is not None:
            if not item_ids:
                return []
            item_placeholders = ",".join("?" for _ in item_ids)
            query += f" AND item_id IN ({item_placeholders})"
            parameters.extend(item_ids)
        query += " ORDER BY item_id LIMIT ?"
        parameters.append(max(0, int(max_items)))
        selected = [row[0] for row in connection.execute(query, parameters)]
        now = datetime.now(timezone.utc).isoformat()
        connection.executemany(
            "UPDATE items SET status='dispatching', attempts=attempts+1, error='', "
            "updated_at=? WHERE item_id=?", [(now, item_id) for item_id in selected]
        )
        return selected


def update_item(path: str | Path, item_id: str, status: str, *, task_id: str = "",
                error: str = "", result: dict[str, Any] | None = None) -> None:
    if status not in {"dispatching", "enqueued", *TERMINAL_STATES}:
        raise ValueError(f"unsupported checkpoint status: {status}")
    with _connect(path) as connection:
        status_guard = " AND status='dispatching'" if status == "enqueued" else ""
        changed = connection.execute(
            "UPDATE items SET status=?, task_id=CASE WHEN ?='' THEN task_id ELSE ? END, "
            "error=?, result_json=?, updated_at=? WHERE item_id=?" + status_guard,
            (status, task_id, task_id, error[:500],
             json.dumps(result or {}, ensure_ascii=False),
             datetime.now(timezone.utc).isoformat(), item_id),
        ).rowcount
        if changed != 1 and status == "enqueued":
            current = connection.execute(
                "SELECT status FROM items WHERE item_id=?", (item_id,)
            ).fetchone()
            if current and current[0] in TERMINAL_STATES:
                return
        if changed != 1:
            raise ValueError("checkpoint does not contain dispatched item")


def checkpoint_report(path: str | Path) -> dict[str, Any]:
    with _connect(path) as connection:
        metadata = dict(connection.execute("SELECT key, value FROM metadata").fetchall())
        counts = {row[0]: int(row[1]) for row in connection.execute(
            "SELECT status, COUNT(*) FROM items GROUP BY status"
        )}
        total = sum(counts.values())
        succeeded = counts.get("succeeded", 0)
        skipped = counts.get("distilled-skip", 0)
        failed = counts.get("failed", 0)
        enqueued = counts.get("enqueued", 0) + counts.get("dispatching", 0)
        remaining = counts.get("planned", 0)
        return {
            "planned": total, "enqueued": enqueued,
            "succeeded": succeeded, "distilled_skip": skipped,
            "failed": failed, "remaining": remaining,
            "already_completed": succeeded + skipped,
            "terminal": succeeded + skipped + failed,
            "manifest_sha256": metadata.get("manifest_sha256", ""),
            "platform": metadata.get("platform", ""),
            "allow_cloud": json.loads(metadata.get("allow_cloud", "false")),
            "synthesize": json.loads(metadata.get("synthesize", "false")),
        }
