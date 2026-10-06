"""SQLite-backed configuration, grant, session, and approval storage."""

from __future__ import annotations

import json
import sqlite3
import struct
import threading
import uuid
from datetime import datetime, timedelta
from functools import lru_cache
from pathlib import Path

from config import get_settings, hfl_share_session_ttl
from modules.hfl_shares.models import (
    ChatMessage,
    ScopeSnapshot,
    ShareConfiguration,
    ShareGrant,
    ShareGrantSummary,
    utc_now,
)


_SCHEMA = """
PRAGMA journal_mode=WAL;
PRAGMA foreign_keys=ON;
CREATE TABLE IF NOT EXISTS configurations (
    id TEXT PRIMARY KEY,
    payload TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS shares (
    id TEXT PRIMARY KEY,
    configuration_id TEXT NOT NULL DEFAULT '',
    name TEXT NOT NULL,
    token_hash TEXT NOT NULL UNIQUE,
    pin_hash TEXT NOT NULL DEFAULT '',
    auth_mode TEXT NOT NULL,
    allowed_email TEXT NOT NULL DEFAULT '',
    snapshot TEXT NOT NULL,
    created_at TEXT NOT NULL,
    expires_at TEXT NOT NULL,
    status TEXT NOT NULL,
    single_use INTEGER NOT NULL,
    device_limit INTEGER NOT NULL,
    browser_redemption_limit INTEGER NOT NULL DEFAULT 0,
    no_expiry INTEGER NOT NULL DEFAULT 0,
    instant INTEGER NOT NULL DEFAULT 0,
    live_updates INTEGER NOT NULL DEFAULT 0,
    live_configuration TEXT NOT NULL DEFAULT '',
    snapshot_entry_count INTEGER NOT NULL DEFAULT 0,
    redeemed_at TEXT NOT NULL DEFAULT '',
    revoked_at TEXT NOT NULL DEFAULT '',
    pin_failures INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS share_handoffs (
    share_id TEXT PRIMARY KEY REFERENCES shares(id) ON DELETE CASCADE,
    encrypted_link TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS browser_redemptions (
    share_id TEXT NOT NULL REFERENCES shares(id) ON DELETE CASCADE,
    browser_hash TEXT NOT NULL,
    count INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY(share_id, browser_hash)
);
CREATE TABLE IF NOT EXISTS sessions (
    id TEXT PRIMARY KEY,
    share_id TEXT NOT NULL REFERENCES shares(id) ON DELETE CASCADE,
    secret_hash TEXT NOT NULL,
    created_at TEXT NOT NULL,
    expires_at TEXT NOT NULL,
    revoked_at TEXT NOT NULL DEFAULT ''
);
CREATE TABLE IF NOT EXISTS access_requests (
    id TEXT PRIMARY KEY,
    share_id TEXT NOT NULL REFERENCES shares(id) ON DELETE CASCADE,
    secret_hash TEXT NOT NULL,
    status TEXT NOT NULL,
    created_at TEXT NOT NULL,
    expires_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS chat_events (
    id TEXT PRIMARY KEY,
    share_id TEXT NOT NULL REFERENCES shares(id) ON DELETE CASCADE,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS pin_failure_events (
    id TEXT PRIMARY KEY,
    share_id TEXT NOT NULL REFERENCES shares(id) ON DELETE CASCADE,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS chat_messages (
    id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
    share_id TEXT NOT NULL REFERENCES shares(id) ON DELETE CASCADE,
    role TEXT NOT NULL,
    content TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS share_embeddings (
    share_id TEXT NOT NULL REFERENCES shares(id) ON DELETE CASCADE,
    entry_id TEXT NOT NULL,
    model_name TEXT NOT NULL,
    content_hash TEXT NOT NULL,
    dimensions INTEGER NOT NULL,
    embedding BLOB NOT NULL,
    created_at TEXT NOT NULL,
    PRIMARY KEY(share_id, entry_id, model_name)
);
CREATE INDEX IF NOT EXISTS idx_sessions_share ON sessions(share_id);
CREATE INDEX IF NOT EXISTS idx_requests_share ON access_requests(share_id);
CREATE INDEX IF NOT EXISTS idx_chat_events_share ON chat_events(share_id, created_at);
CREATE INDEX IF NOT EXISTS idx_pin_failure_events_share
ON pin_failure_events(share_id, created_at);
CREATE INDEX IF NOT EXISTS idx_chat_messages_session
ON chat_messages(session_id, created_at);
CREATE INDEX IF NOT EXISTS idx_share_embeddings_share
ON share_embeddings(share_id, model_name);
CREATE INDEX IF NOT EXISTS idx_shares_owner_list
ON shares(instant, created_at DESC);
"""


class ShareStore:
    def __init__(self, path: Path) -> None:
        self.path = Path(path).expanduser().resolve()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        with self._connect() as connection:
            connection.executescript(_SCHEMA)
            share_columns = {
                row["name"]
                for row in connection.execute("PRAGMA table_info(shares)")
            }
            if "no_expiry" not in share_columns:
                connection.execute(
                    "ALTER TABLE shares "
                    "ADD COLUMN no_expiry INTEGER NOT NULL DEFAULT 0"
                )
            if "browser_redemption_limit" not in share_columns:
                connection.execute(
                    "ALTER TABLE shares ADD COLUMN browser_redemption_limit "
                    "INTEGER NOT NULL DEFAULT 0"
                )
            if "instant" not in share_columns:
                connection.execute(
                    "ALTER TABLE shares "
                    "ADD COLUMN instant INTEGER NOT NULL DEFAULT 0"
                )
            if "live_updates" not in share_columns:
                connection.execute(
                    "ALTER TABLE shares "
                    "ADD COLUMN live_updates INTEGER NOT NULL DEFAULT 0"
                )
            if "live_configuration" not in share_columns:
                connection.execute(
                    "ALTER TABLE shares "
                    "ADD COLUMN live_configuration TEXT NOT NULL DEFAULT ''"
                )
            if "snapshot_entry_count" not in share_columns:
                connection.execute(
                    "ALTER TABLE shares "
                    "ADD COLUMN snapshot_entry_count INTEGER NOT NULL DEFAULT 0"
                )
                connection.execute(
                    "UPDATE shares SET snapshot_entry_count="
                    "COALESCE(json_array_length(snapshot, '$.entries'), 0)"
                )

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path, timeout=15)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys=ON")
        return connection

    def get_share_embeddings(
        self,
        share_id: str,
        *,
        model_name: str,
    ) -> dict[str, dict[str, object]]:
        """Return vectors stored for one immutable share and model."""
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT e.* FROM share_embeddings e
                JOIN shares sh ON sh.id=e.share_id
                WHERE e.share_id=? AND e.model_name=?
                """,
                (share_id, model_name),
            ).fetchall()
        result: dict[str, dict[str, object]] = {}
        for row in rows:
            dimensions = int(row["dimensions"])
            blob = bytes(row["embedding"])
            if dimensions <= 0 or len(blob) != dimensions * 4:
                continue
            result[str(row["entry_id"])] = {
                "content_hash": str(row["content_hash"]),
                "embedding": struct.unpack(f"<{dimensions}f", blob),
            }
        return result

    def upsert_share_embeddings(
        self,
        share_id: str,
        *,
        model_name: str,
        rows: list[dict[str, object]],
    ) -> None:
        """Persist locally generated vectors for one immutable share."""
        if not rows:
            return
        now = utc_now().isoformat()
        with self._lock, self._connect() as connection:
            exists = connection.execute(
                "SELECT 1 FROM shares WHERE id=?", (share_id,)
            ).fetchone()
            if not exists:
                raise ValueError("Active share not found for local indexing.")
            connection.execute(
                "DELETE FROM share_embeddings WHERE share_id=? AND model_name<>?",
                (share_id, model_name),
            )
            for row in rows:
                vector = tuple(float(value) for value in row["embedding"])
                connection.execute(
                    """
                    INSERT INTO share_embeddings(
                        share_id, entry_id, model_name, content_hash,
                        dimensions, embedding, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(share_id, entry_id, model_name) DO UPDATE SET
                        content_hash=excluded.content_hash,
                        dimensions=excluded.dimensions,
                        embedding=excluded.embedding,
                        created_at=excluded.created_at
                    """,
                    (
                        share_id,
                        str(row["entry_id"]),
                        model_name,
                        str(row["content_hash"]),
                        len(vector),
                        struct.pack(f"<{len(vector)}f", *vector),
                        now,
                    ),
                )

    @staticmethod
    def _configuration_payload(payload: dict) -> ShareConfiguration:
        for field in (
            "sources",
            "tags",
            "selected_entry_ids",
            "disabled_reference_ids",
        ):
            payload[field] = tuple(payload.get(field) or [])
        if "context_prompt" not in payload:
            payload["context_prompt"] = "\n".join(
                str(item) for item in payload.pop("test_prompts", ()) if item
            )
        else:
            payload.pop("test_prompts", None)
        return ShareConfiguration(**payload)

    @staticmethod
    def _configuration(row: sqlite3.Row) -> ShareConfiguration:
        return ShareStore._configuration_payload(json.loads(row["payload"]))

    @staticmethod
    def _grant(row: sqlite3.Row) -> ShareGrant:
        live_configuration = str(row["live_configuration"] or "")
        return ShareGrant(
            id=row["id"],
            configuration_id=row["configuration_id"],
            name=row["name"],
            auth_mode=row["auth_mode"],
            allowed_email=row["allowed_email"],
            snapshot=ScopeSnapshot.from_record(json.loads(row["snapshot"])),
            created_at=row["created_at"],
            expires_at=row["expires_at"],
            status=row["status"],
            single_use=bool(row["single_use"]),
            device_limit=int(row["device_limit"]),
            browser_redemption_limit=int(row["browser_redemption_limit"]),
            no_expiry=bool(row["no_expiry"]),
            instant=bool(row["instant"]),
            live_updates=bool(row["live_updates"]),
            live_configuration=(
                ShareStore._configuration_payload(json.loads(live_configuration))
                if live_configuration
                else None
            ),
            redeemed_at=row["redeemed_at"],
            revoked_at=row["revoked_at"],
            pin_failures=int(row["pin_failures"]),
        )

    @staticmethod
    def _grant_summary(row: sqlite3.Row) -> ShareGrantSummary:
        return ShareGrantSummary(
            id=row["id"],
            configuration_id=row["configuration_id"],
            name=row["name"],
            auth_mode=row["auth_mode"],
            allowed_email=row["allowed_email"],
            created_at=row["created_at"],
            expires_at=row["expires_at"],
            status=row["status"],
            single_use=bool(row["single_use"]),
            device_limit=int(row["device_limit"]),
            browser_redemption_limit=int(row["browser_redemption_limit"]),
            entry_count=int(row["snapshot_entry_count"]),
            no_expiry=bool(row["no_expiry"]),
            instant=bool(row["instant"]),
            live_updates=bool(row["live_updates"]),
            redeemed_at=row["redeemed_at"],
            revoked_at=row["revoked_at"],
            pin_failures=int(row["pin_failures"]),
        )

    def save_configuration(
        self, configuration: ShareConfiguration
    ) -> ShareConfiguration:
        now = utc_now().isoformat()
        saved = configuration.saved(
            configuration_id=configuration.id or str(uuid.uuid4()),
            now=now,
        )
        payload = json.dumps(saved.to_record(), ensure_ascii=False)
        with self._lock, self._connect() as connection:
            connection.execute(
                """
                INSERT INTO configurations(id, payload, created_at, updated_at)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    payload=excluded.payload, updated_at=excluded.updated_at
                """,
                (saved.id, payload, saved.created_at, saved.updated_at),
            )
        return saved

    def list_configurations(self) -> list[ShareConfiguration]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT * FROM configurations ORDER BY updated_at DESC"
            ).fetchall()
        return [self._configuration(row) for row in rows]

    def get_configuration(self, configuration_id: str) -> ShareConfiguration | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM configurations WHERE id=?", (configuration_id,)
            ).fetchone()
        return self._configuration(row) if row else None

    def delete_configuration(self, configuration_id: str) -> bool:
        with self._lock, self._connect() as connection:
            result = connection.execute(
                "DELETE FROM configurations WHERE id=?", (configuration_id,)
            )
        return result.rowcount > 0

    def create_share(
        self,
        *,
        configuration_id: str,
        name: str,
        token_hash: str,
        encrypted_link: str = "",
        pin_hash: str,
        auth_mode: str,
        allowed_email: str,
        snapshot: ScopeSnapshot,
        ttl_seconds: int,
        no_expiry: bool = False,
        instant: bool = False,
        live_configuration: ShareConfiguration | None = None,
        single_use: bool,
        device_limit: int,
    ) -> ShareGrant:
        now = utc_now()
        grant = ShareGrant(
            id=str(uuid.uuid4()),
            configuration_id=configuration_id,
            name=name,
            auth_mode=auth_mode,
            allowed_email=allowed_email,
            snapshot=snapshot,
            created_at=now.isoformat(),
            expires_at=(
                ""
                if no_expiry
                else (now + timedelta(seconds=ttl_seconds)).isoformat()
            ),
            status="active",
            single_use=single_use,
            device_limit=device_limit,
            no_expiry=no_expiry,
            instant=instant,
            live_updates=live_configuration is not None,
            live_configuration=live_configuration,
        )
        with self._lock, self._connect() as connection:
            connection.execute(
                """
                INSERT INTO shares(
                    id, configuration_id, name, token_hash, pin_hash,
                    auth_mode, allowed_email, snapshot, created_at, expires_at,
                    status, single_use, device_limit, no_expiry, instant,
                    live_updates, live_configuration, snapshot_entry_count
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    grant.id, configuration_id, name, token_hash, pin_hash,
                    auth_mode, allowed_email,
                    json.dumps(snapshot.to_record(), ensure_ascii=False),
                    grant.created_at, grant.expires_at, "active",
                    int(single_use), int(device_limit), int(no_expiry),
                    int(instant),
                    int(live_configuration is not None),
                    (
                        json.dumps(live_configuration.to_record(), ensure_ascii=False)
                        if live_configuration
                        else ""
                    ),
                    len(snapshot.entries),
                ),
            )
            if encrypted_link:
                connection.execute(
                    "INSERT INTO share_handoffs(share_id, encrypted_link) VALUES (?, ?)",
                    (grant.id, encrypted_link),
                )
        return grant

    def get_share_link(self, share_id: str) -> str:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT encrypted_link FROM share_handoffs WHERE share_id=?",
                (share_id,),
            ).fetchone()
        return str(row["encrypted_link"]) if row else ""

    def update_share_snapshot(self, share_id: str, snapshot: ScopeSnapshot) -> bool:
        with self._lock, self._connect() as connection:
            result = connection.execute(
                "UPDATE shares SET snapshot=?, snapshot_entry_count=? "
                "WHERE id=? AND live_updates=1",
                (
                    json.dumps(snapshot.to_record(), ensure_ascii=False),
                    len(snapshot.entries),
                    share_id,
                ),
            )
        return result.rowcount > 0

    def count_shares(self, *, include_instant: bool = False) -> int:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT COUNT(*) AS count FROM shares "
                + ("" if include_instant else "WHERE instant=0")
            ).fetchone()
        return int(row["count"])

    def list_share_summaries(
        self,
        *,
        limit: int,
        offset: int = 0,
        include_instant: bool = False,
    ) -> list[ShareGrantSummary]:
        """Return one metadata-only page without reading snapshot JSON."""
        page_size = max(1, int(limit))
        page_offset = max(0, int(offset))
        columns = (
            "id, configuration_id, name, auth_mode, allowed_email, "
            "created_at, expires_at, status, single_use, device_limit, "
            "snapshot_entry_count, no_expiry, instant, live_updates, "
            "redeemed_at, revoked_at, pin_failures, browser_redemption_limit"
        )
        with self._connect() as connection:
            rows = connection.execute(
                f"SELECT {columns} FROM shares "
                + ("" if include_instant else "WHERE instant=0 ")
                + "ORDER BY created_at DESC LIMIT ? OFFSET ?",
                (page_size, page_offset),
            ).fetchall()
        return [self._grant_summary(row) for row in rows]

    def list_shares(self, *, include_instant: bool = False) -> list[ShareGrant]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT * FROM shares "
                + ("" if include_instant else "WHERE instant=0 ")
                + "ORDER BY created_at DESC"
            ).fetchall()
        return [self._grant(row) for row in rows]

    def get_share(self, share_id: str) -> ShareGrant | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM shares WHERE id=?", (share_id,)
            ).fetchone()
        return self._grant(row) if row else None

    def get_share_by_token_hash(self, token_hash: str) -> ShareGrant | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM shares WHERE token_hash=?", (token_hash,)
            ).fetchone()
        return self._grant(row) if row else None

    def pin_hash_for_share(self, share_id: str) -> str:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT pin_hash FROM shares WHERE id=?", (share_id,)
            ).fetchone()
        return str(row["pin_hash"]) if row else ""

    def record_pin_failure(self, share_id: str) -> int:
        now = utc_now().isoformat()
        with self._lock, self._connect() as connection:
            connection.execute(
                "INSERT INTO pin_failure_events(id, share_id, created_at) "
                "VALUES (?, ?, ?)",
                (str(uuid.uuid4()), share_id, now),
            )
            connection.execute(
                "UPDATE shares SET pin_failures=pin_failures+1 WHERE id=?",
                (share_id,),
            )
            row = connection.execute(
                "SELECT pin_failures FROM shares WHERE id=?", (share_id,)
            ).fetchone()
        return int(row["pin_failures"]) if row else 0

    def pin_rate_limited(
        self,
        share_id: str,
        limit: int,
        window_seconds: int,
    ) -> bool:
        """Temporarily limit failures without permanently locking a share."""
        cutoff = (
            utc_now() - timedelta(seconds=max(1, int(window_seconds)))
        ).isoformat()
        with self._lock, self._connect() as connection:
            connection.execute(
                "DELETE FROM pin_failure_events WHERE created_at<?", (cutoff,)
            )
            count = connection.execute(
                "SELECT COUNT(*) AS count FROM pin_failure_events "
                "WHERE share_id=? AND created_at>=?",
                (share_id, cutoff),
            ).fetchone()["count"]
        return int(count) >= max(1, int(limit))

    def clear_recent_pin_failures(self, share_id: str) -> None:
        with self._lock, self._connect() as connection:
            connection.execute(
                "DELETE FROM pin_failure_events WHERE share_id=?", (share_id,)
            )

    def set_browser_redemption_limit(self, share_id: str, limit: int) -> bool:
        """Enable a per-browser allowance on an existing anonymous QR grant."""
        if isinstance(limit, bool) or not isinstance(limit, int) or limit < 1:
            raise ValueError("Browser redemption limit must be a positive integer.")
        with self._lock, self._connect() as connection:
            result = connection.execute(
                "UPDATE shares SET browser_redemption_limit=?, single_use=0 "
                "WHERE id=? AND auth_mode='qr' AND status='active'",
                (limit, share_id),
            )
        return result.rowcount == 1

    def browser_redemption_count(self, share_id: str, browser_hash: str) -> int:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT count FROM browser_redemptions WHERE share_id=? AND browser_hash=?",
                (share_id, browser_hash),
            ).fetchone()
        return int(row["count"]) if row else 0

    def create_session(
        self, share_id: str, secret_hash: str, *, browser_hash: str = ""
    ) -> tuple[str, str] | None:
        now = utc_now()
        with self._lock, self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT * FROM shares WHERE id=?", (share_id,)
            ).fetchone()
            if not row:
                return None
            grant = self._grant(row)
            if not grant.available:
                return None
            if grant.browser_redemption_limit:
                if not browser_hash:
                    return None
                usage = connection.execute(
                    "SELECT count FROM browser_redemptions WHERE share_id=? AND browser_hash=?",
                    (share_id, browser_hash),
                ).fetchone()
                if usage and usage["count"] >= grant.browser_redemption_limit:
                    return None
            connection.execute(
                "DELETE FROM sessions WHERE share_id=? AND expires_at<=?",
                (share_id, now.isoformat()),
            )
            active_count = connection.execute(
                """
                SELECT COUNT(*) AS count FROM sessions
                WHERE share_id=? AND revoked_at='' AND expires_at>?
                """,
                (share_id, now.isoformat()),
            ).fetchone()["count"]
            if active_count >= grant.device_limit:
                return None
            if grant.single_use and grant.redeemed_at:
                return None
            session_id = str(uuid.uuid4())
            session_ttl = hfl_share_session_ttl()
            session_limit = now + timedelta(seconds=session_ttl)
            expires_at = (
                session_limit
                if grant.no_expiry
                else min(datetime.fromisoformat(grant.expires_at), session_limit)
            ).isoformat()
            connection.execute(
                """
                INSERT INTO sessions(
                    id, share_id, secret_hash, created_at, expires_at
                ) VALUES (?, ?, ?, ?, ?)
                """,
                (session_id, share_id, secret_hash, now.isoformat(), expires_at),
            )
            connection.execute(
                """
                UPDATE shares
                SET redeemed_at=CASE WHEN redeemed_at='' THEN ? ELSE redeemed_at END
                WHERE id=?
                """,
                (now.isoformat(), share_id),
            )
            if grant.browser_redemption_limit:
                connection.execute(
                    "INSERT INTO browser_redemptions(share_id,browser_hash,count) VALUES (?,?,1) "
                    "ON CONFLICT(share_id,browser_hash) DO UPDATE SET count=count+1",
                    (share_id, browser_hash),
                )
        return session_id, expires_at

    def active_session_count(self, share_id: str) -> int:
        now = utc_now().isoformat()
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT COUNT(*) AS count FROM sessions
                WHERE share_id=? AND revoked_at='' AND expires_at>?
                """,
                (share_id, now),
            ).fetchone()
        return int(row["count"]) if row else 0

    def revoke_session(self, session_id: str) -> bool:
        now = utc_now().isoformat()
        with self._lock, self._connect() as connection:
            result = connection.execute(
                """
                UPDATE sessions SET revoked_at=?
                WHERE id=? AND revoked_at='' AND expires_at>?
                """,
                (now, session_id, now),
            )
        return result.rowcount > 0

    def validate_session(
        self, session_id: str, secret_hash: str
    ) -> ShareGrant | None:
        now = utc_now().isoformat()
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT sh.* FROM sessions s
                JOIN shares sh ON sh.id=s.share_id
                WHERE s.id=? AND s.secret_hash=? AND s.revoked_at=''
                  AND s.expires_at>? AND sh.status='active'
                  AND (sh.no_expiry=1 OR sh.expires_at>?)
                """,
                (session_id, secret_hash, now, now),
            ).fetchone()
        return self._grant(row) if row else None

    def revoke_session(self, session_id: str) -> bool:
        now = utc_now().isoformat()
        with self._lock, self._connect() as connection:
            result = connection.execute(
                """
                UPDATE sessions SET revoked_at=?
                WHERE id=? AND revoked_at=''
                """,
                (now, session_id),
            )
        return result.rowcount > 0

    def revoke_share(self, share_id: str) -> bool:
        now = utc_now().isoformat()
        with self._lock, self._connect() as connection:
            result = connection.execute(
                """
                UPDATE shares SET status='revoked', revoked_at=?
                WHERE id=? AND status='active'
                """,
                (now, share_id),
            )
            connection.execute(
                "UPDATE sessions SET revoked_at=? WHERE share_id=? AND revoked_at=''",
                (now, share_id),
            )
            connection.execute(
                "UPDATE access_requests SET status='revoked' WHERE share_id=?",
                (share_id,),
            )
        return result.rowcount > 0

    def create_access_request(
        self, share_id: str, secret_hash: str
    ) -> tuple[str, str] | None:
        now = utc_now()
        request_id = str(uuid.uuid4())
        expires_at = now + timedelta(hours=1)
        with self._lock, self._connect() as connection:
            pending = connection.execute(
                """
                SELECT COUNT(*) AS count FROM access_requests
                WHERE share_id=? AND status='pending' AND expires_at>?
                """,
                (share_id, now.isoformat()),
            ).fetchone()["count"]
            if pending >= 5:
                return None
            connection.execute(
                """
                INSERT INTO access_requests(
                    id, share_id, secret_hash, status, created_at, expires_at
                ) VALUES (?, ?, ?, 'pending', ?, ?)
                """,
                (
                    request_id, share_id, secret_hash,
                    now.isoformat(), expires_at.isoformat(),
                ),
            )
        return request_id, expires_at.isoformat()

    def allow_chat(self, share_id: str, limit: int) -> bool:
        """Atomically reserve one model query inside a rolling one-hour window."""
        now = utc_now()
        cutoff = (now - timedelta(hours=1)).isoformat()
        with self._lock, self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            connection.execute(
                "DELETE FROM chat_events WHERE created_at<?", (cutoff,)
            )
            count = connection.execute(
                "SELECT COUNT(*) AS count FROM chat_events WHERE share_id=?",
                (share_id,),
            ).fetchone()["count"]
            if count >= max(1, int(limit)):
                return False
            connection.execute(
                "INSERT INTO chat_events(id, share_id, created_at) VALUES (?, ?, ?)",
                (str(uuid.uuid4()), share_id, now.isoformat()),
            )
        return True

    def add_chat_message(
        self,
        *,
        session_id: str,
        share_id: str,
        role: str,
        content: str,
    ) -> ChatMessage:
        if role not in {"user", "assistant"}:
            raise ValueError("Unsupported chat role.")
        message = ChatMessage(
            id=str(uuid.uuid4()),
            session_id=session_id,
            share_id=share_id,
            role=role,
            content=content,
            created_at=utc_now().isoformat(),
        )
        with self._lock, self._connect() as connection:
            belongs = connection.execute(
                "SELECT 1 FROM sessions WHERE id=? AND share_id=?",
                (session_id, share_id),
            ).fetchone()
            if not belongs:
                raise ValueError("Chat session is unavailable.")
            connection.execute(
                """
                INSERT INTO chat_messages(
                    id, session_id, share_id, role, content, created_at
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    message.id,
                    message.session_id,
                    message.share_id,
                    message.role,
                    message.content,
                    message.created_at,
                ),
            )
        return message

    def list_chat_messages(
        self,
        session_id: str,
        share_id: str,
        *,
        limit: int = 40,
    ) -> tuple[ChatMessage, ...]:
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT * FROM (
                    SELECT * FROM chat_messages
                    WHERE session_id=? AND share_id=?
                    ORDER BY created_at DESC
                    LIMIT ?
                ) ORDER BY created_at
                """,
                (session_id, share_id, max(1, int(limit))),
            ).fetchall()
        return tuple(ChatMessage(**dict(row)) for row in rows)

    def list_pending_requests(self) -> list[dict[str, str]]:
        now = utc_now().isoformat()
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT r.id, r.share_id, r.created_at, sh.name
                FROM access_requests r JOIN shares sh ON sh.id=r.share_id
                WHERE r.status='pending' AND r.expires_at>?
                ORDER BY r.created_at
                """,
                (now,),
            ).fetchall()
        return [dict(row) for row in rows]

    def approve_request(self, request_id: str) -> bool:
        with self._lock, self._connect() as connection:
            result = connection.execute(
                """
                UPDATE access_requests SET status='approved'
                WHERE id=? AND status='pending'
                """,
                (request_id,),
            )
        return result.rowcount > 0

    def get_access_request(
        self, request_id: str, secret_hash: str
    ) -> dict[str, str] | None:
        now = utc_now().isoformat()
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT * FROM access_requests
                WHERE id=? AND secret_hash=? AND expires_at>?
                """,
                (request_id, secret_hash, now),
            ).fetchone()
        return dict(row) if row else None

    def consume_approved_request(self, request_id: str) -> None:
        with self._lock, self._connect() as connection:
            connection.execute(
                """
                UPDATE access_requests SET status='consumed'
                WHERE id=? AND status='approved'
                """,
                (request_id,),
            )


@lru_cache(maxsize=1)
def get_share_store() -> ShareStore:
    return ShareStore(Path(get_settings().hfl_share_store_path))


def reset_share_store() -> None:
    get_share_store.cache_clear()
