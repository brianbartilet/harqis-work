"""Durable, leased dispatch state for reviewed Meta archive manifests."""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable


TERMINAL_STATES = {"succeeded", "distilled-skip", "failed"}
ACTIVE_TASK_STATES = {"RECEIVED", "STARTED", "RETRY"}
FAILED_TASK_STATES = {"FAILURE", "REVOKED", "LOST"}


@dataclass(frozen=True)
class TaskSnapshot:
    state: str
    result: dict[str, Any] | None = None
    error: str = ""


def _connect(path: str | Path) -> sqlite3.Connection:
    connection = sqlite3.connect(str(path), timeout=30)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA journal_mode=WAL")
    return connection


def _now(value: datetime | None = None) -> datetime:
    current = value or datetime.now(timezone.utc)
    return current if current.tzinfo else current.replace(tzinfo=timezone.utc)


def _lease_expiry(current: datetime, lease_seconds: int) -> str:
    return (current + timedelta(seconds=max(1, int(lease_seconds)))).isoformat()


def _ensure_lease_columns(connection: sqlite3.Connection) -> None:
    columns = {row[1] for row in connection.execute("PRAGMA table_info(items)")}
    for name in ("reserved_at", "lease_expires_at"):
        if name not in columns:
            connection.execute(f"ALTER TABLE items ADD COLUMN {name} TEXT NOT NULL DEFAULT ''")


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
                updated_at TEXT NOT NULL,
                reserved_at TEXT NOT NULL DEFAULT '',
                lease_expires_at TEXT NOT NULL DEFAULT ''
            );
        """)
        _ensure_lease_columns(connection)
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
        now = _now().isoformat()
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
                  retry_failed: bool = False, lease_seconds: int = 300,
                  now: datetime | None = None) -> list[str]:
    allowed = ["planned"] + (["failed"] if retry_failed else [])
    current = _now(now)
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
        connection.executemany(
            "UPDATE items SET status='dispatching', task_id='', attempts=attempts+1, "
            "error='', reserved_at=?, lease_expires_at=?, updated_at=? WHERE item_id=?",
            [(current.isoformat(), _lease_expiry(current, lease_seconds),
              current.isoformat(), item_id) for item_id in selected],
        )
        return selected


def update_item(path: str | Path, item_id: str, status: str, *, task_id: str = "",
                error: str = "", result: dict[str, Any] | None = None,
                lease_seconds: int = 0, now: datetime | None = None) -> None:
    if status not in {"planned", "dispatching", "enqueued", *TERMINAL_STATES}:
        raise ValueError(f"unsupported checkpoint status: {status}")
    current = _now(now)
    lease_expires = _lease_expiry(current, lease_seconds) if lease_seconds else ""
    with _connect(path) as connection:
        status_guard = (
            " AND status IN ('dispatching', 'enqueued')" if status == "enqueued" else ""
        )
        changed = connection.execute(
            "UPDATE items SET status=?, task_id=CASE WHEN ?='planned' THEN '' "
            "WHEN ?='' THEN task_id ELSE ? END, "
            "error=?, result_json=?, lease_expires_at=?, updated_at=? WHERE item_id=?"
            + status_guard,
            (status, status, task_id, task_id, error[:500],
             json.dumps(result or {}, ensure_ascii=False), lease_expires,
             current.isoformat(), item_id),
        ).rowcount
        if changed != 1 and status == "enqueued":
            existing = connection.execute(
                "SELECT status FROM items WHERE item_id=?", (item_id,)
            ).fetchone()
            if existing and existing[0] in TERMINAL_STATES:
                return
        if changed != 1:
            raise ValueError("checkpoint does not contain dispatched item")


def reconcile_items(path: str | Path,
                    state_lookup: Callable[[str], TaskSnapshot], *,
                    now: datetime | None = None, active_lease_seconds: int = 21_600,
                    reclaim_pending: bool = False) -> dict[str, int]:
    """Reconcile stale reservations with Celery/Flower task observations.

    An expired reservation without a task ID is safe to return to ``planned``.
    Ambiguous Celery ``PENDING`` tasks are retained unless an operator invokes
    recovery with ``reclaim_pending=True``. A resolver can return ``LOST`` when
    Flower or broker evidence confirms that the task no longer exists.
    """
    current = _now(now)
    transitions = {"reclaimed": 0, "succeeded": 0, "distilled_skip": 0,
                   "failed": 0, "active": 0, "pending": 0}
    with _connect(path) as connection:
        rows = connection.execute(
            "SELECT item_id, status, task_id, lease_expires_at FROM items "
            "WHERE status IN ('dispatching', 'enqueued') ORDER BY item_id"
        ).fetchall()
    for row in rows:
        expires = datetime.fromisoformat(row["lease_expires_at"]) if row["lease_expires_at"] else current
        if expires.tzinfo is None:
            expires = expires.replace(tzinfo=timezone.utc)
        expired = expires <= current
        task_id = str(row["task_id"] or "")
        if not task_id:
            if row["status"] == "dispatching" and expired:
                update_item(path, row["item_id"], "planned",
                            error="reclaimed-stale-dispatching", now=current)
                transitions["reclaimed"] += 1
            continue
        snapshot = state_lookup(task_id)
        state = snapshot.state.upper()
        if state == "SUCCESS":
            result = snapshot.result or {}
            status = ("distilled-skip" if result.get("skipped") == "distilled-skip"
                      else "succeeded")
            update_item(path, row["item_id"], status, task_id=task_id,
                        result=result, now=current)
            transitions["distilled_skip" if status == "distilled-skip" else "succeeded"] += 1
        elif state in FAILED_TASK_STATES:
            update_item(path, row["item_id"], "failed", task_id=task_id,
                        error=snapshot.error or f"task-{state.casefold()}", now=current)
            transitions["failed"] += 1
        elif state in ACTIVE_TASK_STATES:
            update_item(path, row["item_id"], "enqueued", task_id=task_id,
                        lease_seconds=active_lease_seconds, now=current)
            transitions["active"] += 1
        elif state in {"PENDING", "UNKNOWN"} and expired and reclaim_pending:
            update_item(path, row["item_id"], "failed", task_id=task_id,
                        error="stale-pending-task-reclaimed", now=current)
            transitions["failed"] += 1
        elif state in {"PENDING", "UNKNOWN"}:
            transitions["pending"] += 1
    return transitions


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
