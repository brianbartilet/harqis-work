"""Transactional SQLite state for the Second Brain canonical host."""

from __future__ import annotations

import json
import os
import sqlite3
import threading
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from functools import lru_cache
from pathlib import Path
from typing import Any, Iterable

from workflows.second_brain.models import ContextEvent, FeedItem, ModeDecision, ModeDefinition, isoformat, normalize_modes


DEFAULT_MODE = ModeDefinition(
    mode_id="default",
    name="Default",
    color="#38bdf8",
    keywords=("jira", "meeting", "coding", "review"),
    operation_ids=("jira.changed",),
).to_payload()


DEFAULT_CONFIG = {
    "enabled": True,
    "clients": {"web": True, "telegram": False, "rainmeter": False, "cli": False},
    "disclosure": {
        "web": "owner_full",
        "telegram": "owner_redacted",
        "rainmeter": "local_redacted",
        "cli": "owner_redacted",
    },
    "hermes_enabled": False,
    "reconcile_minutes": 15,
    "chat_retention_hours": 8,
    "modes": [DEFAULT_MODE],
}


_SCHEMA = """
PRAGMA journal_mode=WAL;
PRAGMA foreign_keys=ON;
CREATE TABLE IF NOT EXISTS context_events (
    event_id TEXT PRIMARY KEY,
    observed_at TEXT NOT NULL,
    received_at TEXT NOT NULL,
    source TEXT NOT NULL,
    event_type TEXT NOT NULL,
    sensitivity TEXT NOT NULL,
    expires_at TEXT NOT NULL DEFAULT '',
    correlation_id TEXT NOT NULL,
    payload_json TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_context_events_received ON context_events(received_at DESC);
CREATE TABLE IF NOT EXISTS manual_overrides (
    override_id INTEGER PRIMARY KEY AUTOINCREMENT,
    modes_json TEXT NOT NULL,
    created_at TEXT NOT NULL,
    expires_at TEXT NOT NULL,
    revoked_at TEXT NOT NULL DEFAULT '',
    correlation_id TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_manual_overrides_active ON manual_overrides(expires_at DESC, revoked_at);
CREATE TABLE IF NOT EXISTS mode_decisions (
    decision_id TEXT PRIMARY KEY,
    evaluated_at TEXT NOT NULL,
    valid_until TEXT NOT NULL DEFAULT '',
    correlation_id TEXT NOT NULL,
    payload_json TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_mode_decisions_latest ON mode_decisions(evaluated_at DESC);
CREATE TABLE IF NOT EXISTS workflow_runs (
    run_id TEXT PRIMARY KEY,
    operation_id TEXT NOT NULL,
    state TEXT NOT NULL,
    started_at TEXT NOT NULL,
    finished_at TEXT NOT NULL DEFAULT '',
    correlation_id TEXT NOT NULL,
    task_id TEXT NOT NULL DEFAULT '',
    error_type TEXT NOT NULL DEFAULT '',
    result_json TEXT NOT NULL DEFAULT '{}'
);
CREATE TABLE IF NOT EXISTS feed_items (
    item_id TEXT PRIMARY KEY,
    logical_key TEXT NOT NULL UNIQUE,
    category TEXT NOT NULL,
    priority INTEGER NOT NULL,
    generated_at TEXT NOT NULL,
    expires_at TEXT NOT NULL DEFAULT '',
    content_hash TEXT NOT NULL,
    revision INTEGER NOT NULL,
    payload_json TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_feed_items_rank ON feed_items(priority DESC, generated_at DESC);
CREATE TABLE IF NOT EXISTS feed_revisions (
    revision INTEGER PRIMARY KEY AUTOINCREMENT,
    item_id TEXT NOT NULL,
    logical_key TEXT NOT NULL,
    changed_at TEXT NOT NULL,
    payload_json TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS config_versions (
    version INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at TEXT NOT NULL,
    config_json TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS chat_messages (
    message_id TEXT PRIMARY KEY,
    role TEXT NOT NULL,
    created_at TEXT NOT NULL,
    expires_at TEXT NOT NULL,
    correlation_id TEXT NOT NULL,
    content TEXT NOT NULL,
    citations_json TEXT NOT NULL DEFAULT '[]'
);
CREATE INDEX IF NOT EXISTS idx_chat_messages_created ON chat_messages(created_at DESC);
"""


def default_store_path() -> Path:
    configured = os.environ.get("SECOND_BRAIN_STORE_PATH", "").strip()
    if configured:
        return Path(configured).expanduser().resolve()
    data_root = os.environ.get("HARQIS_DATA_ROOT", "").strip()
    root = Path(data_root).expanduser().resolve() if data_root else Path(__file__).resolve().parents[2] / ".harqis-data"
    return (root / "second-brain.sqlite3").resolve()


class SecondBrainStore:
    def __init__(self, path: Path | str):
        self.path = Path(path).expanduser().resolve()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        with self._connect() as connection:
            connection.executescript(_SCHEMA)
            count = connection.execute("SELECT COUNT(*) FROM config_versions").fetchone()[0]
            if not count:
                connection.execute(
                    "INSERT INTO config_versions(created_at, config_json) VALUES (?, ?)",
                    (isoformat(), json.dumps(DEFAULT_CONFIG, sort_keys=True)),
                )

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path, timeout=15)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA busy_timeout=15000")
        connection.execute("PRAGMA foreign_keys=ON")
        return connection

    def append_context(self, event: ContextEvent) -> bool:
        with self._lock, self._connect() as connection:
            cursor = connection.execute(
                """INSERT OR IGNORE INTO context_events
                   (event_id, observed_at, received_at, source, event_type, sensitivity,
                    expires_at, correlation_id, payload_json)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    event.event_id,
                    event.observed_at,
                    event.received_at,
                    event.source,
                    event.event_type,
                    event.sensitivity,
                    event.expires_at,
                    event.correlation_id,
                    json.dumps(event.to_payload(), sort_keys=True, ensure_ascii=False),
                ),
            )
            return cursor.rowcount == 1

    def recent_context(self, *, limit: int = 50) -> list[dict[str, Any]]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT payload_json FROM context_events ORDER BY received_at DESC LIMIT ?",
                (max(1, min(500, int(limit))),),
            ).fetchall()
        return [json.loads(row["payload_json"]) for row in rows]

    def set_override(self, modes: Iterable[str], *, duration_minutes: int, correlation_id: str) -> dict[str, Any]:
        normalized = normalize_modes(modes)
        available = {mode["mode_id"] for mode in self.list_modes() if mode["enabled"] and not mode["archived"]}
        if set(normalized) - available:
            raise ValueError("manual selection contains an unavailable category")
        if not normalized:
            raise ValueError("manual overrides require at least one mode")
        duration = max(30, min(12 * 60, int(duration_minutes)))
        created = datetime.now(timezone.utc)
        expires = created + timedelta(minutes=duration)
        with self._lock, self._connect() as connection:
            connection.execute(
                "UPDATE manual_overrides SET revoked_at=? WHERE revoked_at='' AND expires_at>?",
                (isoformat(created), isoformat(created)),
            )
            cursor = connection.execute(
                "INSERT INTO manual_overrides(modes_json, created_at, expires_at, correlation_id) VALUES (?, ?, ?, ?)",
                (json.dumps(normalized), isoformat(created), isoformat(expires), correlation_id),
            )
        return {"override_id": cursor.lastrowid, "modes": list(normalized), "expires_at": isoformat(expires)}

    def clear_override(self) -> None:
        now = isoformat()
        with self._lock, self._connect() as connection:
            connection.execute(
                "UPDATE manual_overrides SET revoked_at=? WHERE revoked_at='' AND expires_at>?",
                (now, now),
            )

    def active_override(self, *, now: str | None = None) -> dict[str, Any] | None:
        current = now or isoformat()
        with self._connect() as connection:
            row = connection.execute(
                """SELECT override_id, modes_json, created_at, expires_at, correlation_id
                   FROM manual_overrides
                   WHERE revoked_at='' AND expires_at>?
                   ORDER BY override_id DESC LIMIT 1""",
                (current,),
            ).fetchone()
        if not row:
            return None
        modes = json.loads(row["modes_json"])
        available = {
            mode["mode_id"]
            for mode in self.list_modes()
            if mode["enabled"] and not mode["archived"]
        }
        if not modes or set(modes) - available:
            with self._lock, self._connect() as connection:
                connection.execute(
                    "UPDATE manual_overrides SET revoked_at=? WHERE override_id=?",
                    (current, row["override_id"]),
                )
            return None
        return {
            "override_id": row["override_id"],
            "modes": modes,
            "created_at": row["created_at"],
            "expires_at": row["expires_at"],
            "correlation_id": row["correlation_id"],
        }

    def record_decision(self, decision: ModeDecision) -> None:
        with self._lock, self._connect() as connection:
            connection.execute(
                """INSERT OR IGNORE INTO mode_decisions
                   (decision_id, evaluated_at, valid_until, correlation_id, payload_json)
                   VALUES (?, ?, ?, ?, ?)""",
                (
                    decision.decision_id,
                    decision.evaluated_at,
                    decision.valid_until,
                    decision.correlation_id,
                    json.dumps(decision.to_payload(), sort_keys=True, ensure_ascii=False),
                ),
            )

    def latest_decision(self) -> dict[str, Any] | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT payload_json FROM mode_decisions ORDER BY evaluated_at DESC LIMIT 1"
            ).fetchone()
        return json.loads(row["payload_json"]) if row else None

    def start_run(self, *, run_id: str, operation_id: str, correlation_id: str, task_id: str = "") -> None:
        with self._lock, self._connect() as connection:
            connection.execute(
                """INSERT OR IGNORE INTO workflow_runs
                   (run_id, operation_id, state, started_at, correlation_id, task_id)
                   VALUES (?, ?, 'running', ?, ?, ?)""",
                (run_id, operation_id, isoformat(), correlation_id, task_id),
            )

    def finish_run(self, *, run_id: str, state: str, result: dict[str, Any], error_type: str = "") -> None:
        with self._lock, self._connect() as connection:
            connection.execute(
                """UPDATE workflow_runs SET state=?, finished_at=?, result_json=?, error_type=?
                   WHERE run_id=?""",
                (state, isoformat(), json.dumps(result, sort_keys=True, default=str), error_type, run_id),
            )

    def operation_due(self, operation_id: str, refresh_minutes: int) -> bool:
        """Return whether an operation lacks a recent successful reconciliation."""
        cutoff = isoformat(datetime.now(timezone.utc) - timedelta(minutes=max(1, int(refresh_minutes))))
        with self._connect() as connection:
            row = connection.execute(
                """SELECT 1 FROM workflow_runs
                   WHERE operation_id=? AND state='success' AND finished_at>=?
                   LIMIT 1""",
                (operation_id, cutoff),
            ).fetchone()
        return row is None

    def upsert_feed_item(self, item: FeedItem) -> tuple[dict[str, Any], bool]:
        payload = item.to_payload()
        content_hash = payload["content_hash"]
        with self._lock, self._connect() as connection:
            current = connection.execute(
                "SELECT content_hash, revision FROM feed_items WHERE logical_key=?",
                (item.logical_key,),
            ).fetchone()
            if current and current["content_hash"] == content_hash:
                refreshed = replace(item, revision=int(current["revision"]))
                payload = refreshed.to_payload()
                encoded = json.dumps(payload, sort_keys=True, ensure_ascii=False)
                connection.execute(
                    """UPDATE feed_items SET generated_at=?, expires_at=?, payload_json=?
                       WHERE logical_key=?""",
                    (item.generated_at, item.expires_at, encoded, item.logical_key),
                )
                return payload, False
            revision_cursor = connection.execute(
                "INSERT INTO feed_revisions(item_id, logical_key, changed_at, payload_json) VALUES (?, ?, ?, '{}')",
                (item.item_id, item.logical_key, isoformat()),
            )
            revision = int(revision_cursor.lastrowid)
            persisted = replace(item, revision=revision)
            payload = persisted.to_payload()
            encoded = json.dumps(payload, sort_keys=True, ensure_ascii=False)
            connection.execute(
                "UPDATE feed_revisions SET payload_json=? WHERE revision=?",
                (encoded, revision),
            )
            connection.execute(
                """INSERT INTO feed_items
                   (item_id, logical_key, category, priority, generated_at, expires_at,
                    content_hash, revision, payload_json)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                   ON CONFLICT(logical_key) DO UPDATE SET
                     item_id=excluded.item_id, category=excluded.category,
                     priority=excluded.priority, generated_at=excluded.generated_at,
                     expires_at=excluded.expires_at, content_hash=excluded.content_hash,
                     revision=excluded.revision, payload_json=excluded.payload_json""",
                (
                    item.item_id,
                    item.logical_key,
                    item.category,
                    item.priority,
                    item.generated_at,
                    item.expires_at,
                    content_hash,
                    revision,
                    encoded,
                ),
            )
        return payload, True

    def retire_feed_items(
        self,
        allowed_bindings: Iterable[tuple[str, str]],
    ) -> list[dict[str, Any]]:
        """Expire items whose category no longer owns their source operation.

        Older feed rows predate the explicit ``operation_id`` field, so their
        category-prefixed logical keys are parsed during this rolling migration.
        Revision history remains intact and a new tombstone revision wakes SSE
        clients so they reload the canonical snapshot immediately.
        """
        allowed = {
            (str(category).strip().casefold(), str(operation_id).strip())
            for category, operation_id in allowed_bindings
            if str(category).strip() and str(operation_id).strip()
        }
        retired: list[dict[str, Any]] = []
        current = isoformat()
        with self._lock, self._connect() as connection:
            rows = connection.execute(
                """SELECT item_id, logical_key, category, content_hash, payload_json
                   FROM feed_items WHERE expires_at='' OR expires_at>?""",
                (current,),
            ).fetchall()
            for row in rows:
                payload = json.loads(row["payload_json"])
                operation_id = str(payload.get("operation_id") or "").strip()
                if not operation_id:
                    prefix = f"{row['category']}:"
                    remainder = row["logical_key"][len(prefix):] if row["logical_key"].startswith(prefix) else ""
                    operation_id = remainder.split(":", 1)[0] if ":" in remainder else ""
                if not operation_id or (row["category"], operation_id) in allowed:
                    continue
                revision_cursor = connection.execute(
                    "INSERT INTO feed_revisions(item_id, logical_key, changed_at, payload_json) VALUES (?, ?, ?, '{}')",
                    (row["item_id"], row["logical_key"], current),
                )
                revision = int(revision_cursor.lastrowid)
                tombstone = {
                    **payload,
                    "operation_id": operation_id,
                    "status": "retired",
                    "expires_at": current,
                    "retired_at": current,
                    "retirement_reason": "configuration_changed",
                    "revision": revision,
                }
                encoded = json.dumps(tombstone, sort_keys=True, ensure_ascii=False)
                connection.execute(
                    "UPDATE feed_revisions SET payload_json=? WHERE revision=?",
                    (encoded, revision),
                )
                connection.execute(
                    """UPDATE feed_items
                       SET expires_at=?, content_hash=?, revision=?, payload_json=?
                       WHERE logical_key=?""",
                    (current, f"retired:{revision}:{row['content_hash']}", revision, encoded, row["logical_key"]),
                )
                retired.append(tombstone)
        return retired

    def feed_snapshot(
        self,
        *,
        client: str = "web",
        limit: int = 100,
        modes: Iterable[str] | None = None,
    ) -> dict[str, Any]:
        now = isoformat()
        with self._connect() as connection:
            rows = connection.execute(
                """SELECT payload_json FROM feed_items
                   WHERE expires_at='' OR expires_at>?
                   ORDER BY priority DESC, generated_at DESC LIMIT 500""",
                (now,),
            ).fetchall()
            cursor = connection.execute("SELECT COALESCE(MAX(revision), 0) FROM feed_revisions").fetchone()[0]
        active_modes = set(normalize_modes(modes or ()))
        items = []
        for row in rows:
            payload = json.loads(row["payload_json"])
            if client in payload.get("allowed_clients", []) and (
                not active_modes or payload.get("category") in active_modes
            ):
                items.append(payload)
        return {
            "cursor": int(cursor),
            "items": items[:max(1, min(500, int(limit)))],
            "generated_at": now,
        }

    def changes_after(self, cursor: int, *, client: str = "web", limit: int = 100) -> list[dict[str, Any]]:
        with self._connect() as connection:
            rows = connection.execute(
                """SELECT revision, payload_json FROM feed_revisions
                   WHERE revision>? ORDER BY revision LIMIT ?""",
                (max(0, int(cursor)), max(1, min(500, int(limit)))),
            ).fetchall()
        changes = []
        for row in rows:
            payload = json.loads(row["payload_json"])
            if client in payload.get("allowed_clients", []):
                changes.append({"revision": row["revision"], "item": payload})
        return changes

    def get_config(self) -> dict[str, Any]:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT version, created_at, config_json FROM config_versions ORDER BY version DESC LIMIT 1"
            ).fetchone()
        config = json.loads(row["config_json"]) if row else dict(DEFAULT_CONFIG)
        for key, value in DEFAULT_CONFIG.items():
            config.setdefault(key, value)
        if not config.get("modes"):
            config["modes"] = [DEFAULT_MODE]
        return {"version": int(row["version"]) if row else 0, "created_at": row["created_at"] if row else "", **config}

    def save_config(self, changes: dict[str, Any]) -> dict[str, Any]:
        current = self.get_config()
        config = {key: value for key, value in current.items() if key not in {"version", "created_at"}}
        config.update(changes)
        clients = config.get("clients") or {}
        config["clients"] = {name: bool(clients.get(name, False)) for name in ("web", "telegram", "rainmeter", "cli")}
        config["clients"]["web"] = True
        config["hermes_enabled"] = bool(config.get("hermes_enabled", False))
        config["chat_retention_hours"] = max(1, min(168, int(config.get("chat_retention_hours", 8))))
        modes = [ModeDefinition(**mode).to_payload() for mode in config.get("modes") or [DEFAULT_MODE]]
        if not any(mode["mode_id"] == "default" and not mode["archived"] for mode in modes):
            raise ValueError("the default category cannot be removed or archived")
        config["modes"] = sorted(modes, key=lambda mode: (mode["order"], mode["name"].casefold()))
        with self._lock, self._connect() as connection:
            cursor = connection.execute(
                "INSERT INTO config_versions(created_at, config_json) VALUES (?, ?)",
                (isoformat(), json.dumps(config, sort_keys=True)),
            )
        return {"version": int(cursor.lastrowid), "created_at": isoformat(), **config}

    def update_config(self, *, clients: dict[str, bool], hermes_enabled: bool = False) -> dict[str, Any]:
        return self.save_config({"clients": clients, "hermes_enabled": hermes_enabled})

    def list_modes(self, *, include_archived: bool = False) -> list[dict[str, Any]]:
        modes = self.get_config().get("modes") or [DEFAULT_MODE]
        return [dict(mode) for mode in modes if include_archived or not mode.get("archived")]

    def save_mode(self, mode: ModeDefinition) -> dict[str, Any]:
        config = self.get_config()
        modes = [dict(value) for value in config.get("modes") or []]
        for index, current in enumerate(modes):
            if current["mode_id"] == mode.mode_id:
                modes[index] = mode.to_payload()
                break
        else:
            modes.append(mode.to_payload())
        return self.save_config({"modes": modes})

    def archive_mode(self, mode_id: str) -> dict[str, Any]:
        normalized = normalize_modes((mode_id,))[0]
        if normalized == "default":
            raise ValueError("the default category cannot be archived")
        modes = self.list_modes(include_archived=True)
        found = False
        for mode in modes:
            if mode["mode_id"] == normalized:
                mode["archived"] = True
                mode["enabled"] = False
                found = True
        if not found:
            raise ValueError("category not found")
        return self.save_config({"modes": modes})

    def append_chat(self, *, role: str, content: str, correlation_id: str, citations: Iterable[str] = ()) -> dict[str, Any]:
        if role not in {"user", "assistant"}:
            raise ValueError("unsupported chat role")
        clean = str(content).strip()
        if not clean or len(clean) > 12_000:
            raise ValueError("chat content must contain 1-12000 characters")
        retention = self.get_config().get("chat_retention_hours", 8)
        created = datetime.now(timezone.utc)
        expires = created + timedelta(hours=int(retention))
        message_id = f"chat-{os.urandom(12).hex()}"
        with self._lock, self._connect() as connection:
            connection.execute("DELETE FROM chat_messages WHERE expires_at<=?", (isoformat(created),))
            connection.execute(
                "INSERT INTO chat_messages VALUES (?, ?, ?, ?, ?, ?, ?)",
                (message_id, role, isoformat(created), isoformat(expires), correlation_id, clean, json.dumps(list(citations))),
            )
        return {"message_id": message_id, "role": role, "content": clean, "created_at": isoformat(created), "citations": list(citations)}

    def recent_chat(self, *, limit: int = 50) -> list[dict[str, Any]]:
        now = isoformat()
        with self._connect() as connection:
            rows = connection.execute(
                """SELECT message_id, role, created_at, correlation_id, content, citations_json
                   FROM chat_messages WHERE expires_at>? ORDER BY created_at DESC LIMIT ?""",
                (now, max(1, min(200, int(limit)))),
            ).fetchall()
        return [
            {**dict(row), "citations": json.loads(row["citations_json"])}
            for row in reversed(rows)
        ]


@lru_cache(maxsize=4)
def get_store(path: str = "") -> SecondBrainStore:
    return SecondBrainStore(Path(path).expanduser().resolve() if path else default_store_path())


def reset_store_cache() -> None:
    get_store.cache_clear()
