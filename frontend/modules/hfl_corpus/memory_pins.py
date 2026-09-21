"""Private, owner-scoped Memory Signal categories and annotated date ranges."""

from __future__ import annotations

import sqlite3
from dataclasses import asdict, dataclass
from datetime import date, datetime, timezone
from functools import lru_cache
from pathlib import Path

from config import get_settings


from workflows.hfl.colors import PIN_COLORS


@dataclass(frozen=True)
class PinCategory:
    id: int
    name: str
    color: str
    instructions: str


@dataclass(frozen=True)
class PinRange:
    id: int
    category_id: int
    start_date: str
    end_date: str
    note: str
    updated_at: str
    title: str
    prompt: str
    execution_hour: int = 0
    agent_enabled: bool = False


class MemoryPinStore:
    def __init__(self, path: Path):
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS memory_pin_categories (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT NOT NULL COLLATE NOCASE UNIQUE,
                    color TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS memory_pin_ranges (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    category_id INTEGER NOT NULL REFERENCES memory_pin_categories(id) ON DELETE CASCADE,
                    start_date TEXT NOT NULL,
                    end_date TEXT NOT NULL,
                    note TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    CHECK (start_date <= end_date)
                );
                CREATE INDEX IF NOT EXISTS idx_memory_pin_ranges_dates
                    ON memory_pin_ranges(start_date, end_date);
                """
            )
            self._remove_legacy_color_uniqueness(connection)
            connection.execute("BEGIN IMMEDIATE")
            category_columns = {row['name'] for row in connection.execute('PRAGMA table_info(memory_pin_categories)')}
            range_columns = {row['name'] for row in connection.execute('PRAGMA table_info(memory_pin_ranges)')}
            if 'execution_hour' not in range_columns:
                connection.execute('ALTER TABLE memory_pin_ranges ADD COLUMN execution_hour INTEGER NOT NULL DEFAULT 0')
            if 'agent_enabled' not in range_columns:
                connection.execute('ALTER TABLE memory_pin_ranges ADD COLUMN agent_enabled INTEGER NOT NULL DEFAULT 0')
            if 'instructions' not in category_columns:
                connection.execute("ALTER TABLE memory_pin_categories ADD COLUMN instructions TEXT NOT NULL DEFAULT ''")
            if 'title' not in range_columns:
                connection.execute("ALTER TABLE memory_pin_ranges ADD COLUMN title TEXT NOT NULL DEFAULT ''")
                connection.execute("UPDATE memory_pin_ranges SET title=CASE WHEN trim(note)='' THEN 'Untitled pin' ELSE note END")
            if 'prompt' not in range_columns:
                connection.execute("ALTER TABLE memory_pin_ranges ADD COLUMN prompt TEXT NOT NULL DEFAULT ''")
            if 'archived_at' not in category_columns:
                connection.execute("ALTER TABLE memory_pin_categories ADD COLUMN archived_at TEXT")
            connection.execute("""CREATE TABLE IF NOT EXISTS memory_pin_agent_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                category_id INTEGER NOT NULL REFERENCES memory_pin_categories(id),
                event_key TEXT NOT NULL,
                range_id INTEGER,
                period_title TEXT NOT NULL,
                start_date TEXT NOT NULL,
                end_date TEXT NOT NULL,
                system_prompt TEXT NOT NULL,
                instructions TEXT NOT NULL,
                output TEXT NOT NULL,
                agent TEXT NOT NULL,
                model TEXT NOT NULL,
                status TEXT NOT NULL,
                created_at TEXT NOT NULL,
                UNIQUE(category_id, event_key)
            )""")

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        return connection

    @staticmethod
    def _remove_legacy_color_uniqueness(connection: sqlite3.Connection) -> None:
        """Rebuild legacy category tables whose color column was unique."""
        color_is_unique = False
        for index in connection.execute("PRAGMA index_list(memory_pin_categories)"):
            if not index["unique"]:
                continue
            columns = [
                row["name"]
                for row in connection.execute(
                    f"PRAGMA index_info('{index['name']}')"
                )
            ]
            if columns == ["color"]:
                color_is_unique = True
                break
        if not color_is_unique:
            return

        connection.execute("PRAGMA foreign_keys = OFF")
        try:
            connection.executescript(
                """
                BEGIN IMMEDIATE;
                CREATE TABLE memory_pin_categories_rebuilt (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT NOT NULL COLLATE NOCASE UNIQUE,
                    color TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                INSERT INTO memory_pin_categories_rebuilt
                    (id, name, color, created_at, updated_at)
                SELECT id, name, color, created_at, updated_at
                FROM memory_pin_categories;
                DROP TABLE memory_pin_categories;
                ALTER TABLE memory_pin_categories_rebuilt RENAME TO memory_pin_categories;
                COMMIT;
                """
            )
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.execute("PRAGMA foreign_keys = ON")
        violations = connection.execute("PRAGMA foreign_key_check").fetchall()
        if violations:
            raise sqlite3.IntegrityError("Memory pin migration violated foreign keys.")

    def snapshot(self) -> dict[str, list[dict[str, object]]]:
        with self._connect() as connection:
            categories = connection.execute(
                "SELECT id, name, color, instructions FROM memory_pin_categories WHERE archived_at IS NULL ORDER BY id"
            ).fetchall()
            ranges = connection.execute(
                """SELECT id, category_id, start_date, end_date, note, updated_at, title, prompt, execution_hour, agent_enabled
                   FROM memory_pin_ranges WHERE category_id IN
                   (SELECT id FROM memory_pin_categories WHERE archived_at IS NULL)
                   ORDER BY start_date, end_date, id"""
            ).fetchall()
            archived = connection.execute("SELECT id, name, color, instructions, archived_at FROM memory_pin_categories WHERE archived_at IS NOT NULL ORDER BY name").fetchall()
        # Read legacy opt-ins without activating old pins that never opted in.
        import os
        bridge_path = Path(os.getenv('HFL_AGENT_BRIDGE_STORE_PATH') or self.path.with_name('hfl-agent-bridge.sqlite3')).expanduser()
        subscriptions = {}
        if bridge_path.is_file():
            with sqlite3.connect(bridge_path) as db:
                if db.execute("SELECT 1 FROM sqlite_master WHERE name='agent_subscriptions'").fetchone():
                    subscriptions = dict(db.execute("SELECT source_id,cadence FROM agent_subscriptions WHERE kind='pin'"))
        pin_ranges = [asdict(PinRange(**dict(row))) for row in ranges]
        for pin in pin_ranges:
            if str(pin['id']) in subscriptions:
                pin['agent_enabled'] = subscriptions[str(pin['id'])] != 'off'
        return {
            "categories": [asdict(PinCategory(**dict(row))) for row in categories],
            "ranges": pin_ranges,
            "palette": list(PIN_COLORS),
            "archived_categories": [dict(row) for row in archived],
        }

    def save_category(self, *, category_id: int | None, name: str, color: str, instructions: str = "") -> int:
        if len(instructions) > 20000:
            raise ValueError("Use 20,000 characters or fewer for instructions.")
        name = name.strip()
        if not name or len(name) > 60:
            raise ValueError("Category names must contain 1 to 60 characters.")
        if color not in PIN_COLORS:
            raise ValueError("Choose a color from the Memory Signal palette.")
        now = datetime.now(timezone.utc).isoformat()
        try:
            with self._connect() as connection:
                if category_id:
                    cursor = connection.execute(
                        """UPDATE memory_pin_categories SET name=?, color=?, instructions=?, updated_at=?
                           WHERE id=?""",
                        (name, color, instructions, now, category_id),
                    )
                    if not cursor.rowcount:
                        raise ValueError("That category no longer exists.")
                else:
                    cursor = connection.execute(
                        """INSERT INTO memory_pin_categories(name, color, instructions, created_at, updated_at)
                           VALUES (?, ?, ?, ?, ?)""",
                        (name, color, instructions, now, now),
                    )
                return category_id or cursor.lastrowid
        except sqlite3.IntegrityError as exc:
            raise ValueError("Category names must be unique.") from exc

    def delete_category(self, category_id: int) -> None:
        """Compatibility: old clients now archive instead of deleting data."""
        self.archive_category(category_id)

    def archive_category(self, category_id: int, *, restore: bool = False) -> None:
        with self._connect() as connection:
            now = datetime.now(timezone.utc).isoformat()
            cursor = connection.execute("UPDATE memory_pin_categories SET archived_at=?, updated_at=? WHERE id=?", (None if restore else now, now, category_id))
            if not cursor.rowcount:
                raise ValueError("That category no longer exists.")

    def agent_history(self, category_id: int, *, before_id: int = 0) -> list[dict]:
        with self._connect() as connection:
            return [dict(row) for row in connection.execute(
                "SELECT * FROM memory_pin_agent_events WHERE category_id=? AND (?=0 OR id<?) ORDER BY id DESC LIMIT 20",
                (category_id, before_id, before_id),
            )]

    def record_agent_event(self, *, category_id: int, range_id: int, event_key: str,
                           output: str, agent: str, model: str = "", status: str = "completed",
                           system_prompt: str | None = None) -> int:
        """Append an immutable receipt; retries with the same key keep the original.

        Pass the actual system prompt when available; otherwise snapshot category
        guidance. This records output only and never dispatches agent work.
        """
        if not event_key.strip() or len(event_key) > 200 or not agent.strip() or len(agent) > 200 or len(model) > 200:
            raise ValueError("An event key and agent name of up to 200 characters are required.")
        if status not in {"completed", "failed", "partial"}:
            raise ValueError("Choose completed, failed, or partial for the event outcome.")
        if len(output) > 100000 or (system_prompt is not None and len(system_prompt) > 20000):
            raise ValueError("Output supports 100,000 characters; system prompt supports 20,000.")
        with self._connect() as connection:
            existing = connection.execute("SELECT id FROM memory_pin_agent_events WHERE category_id=? AND event_key=?", (category_id, event_key)).fetchone()
            if existing:
                return existing['id']
            pin = connection.execute("SELECT r.*, c.instructions AS guidance FROM memory_pin_ranges r JOIN memory_pin_categories c ON c.id=r.category_id WHERE r.id=? AND c.id=? AND c.archived_at IS NULL", (range_id, category_id)).fetchone()
            if not pin:
                raise ValueError("Choose a pin belonging to an active category.")
            connection.execute("""INSERT OR IGNORE INTO memory_pin_agent_events
                (category_id,event_key,range_id,period_title,start_date,end_date,system_prompt,instructions,output,agent,model,status,created_at)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""", (category_id,event_key,range_id,pin['title'],pin['start_date'],pin['end_date'],pin['guidance'] if system_prompt is None else system_prompt,pin['prompt'],output,agent,model,status,datetime.now(timezone.utc).isoformat()))
            return connection.execute("SELECT id FROM memory_pin_agent_events WHERE category_id=? AND event_key=?", (category_id,event_key)).fetchone()['id']

    def record_execution_snapshot(self, run: dict) -> None:
        """Project a bridge receipt using dispatch-time instructions, even after edits."""
        snap, result = run['snapshot'], run['result']
        pin = snap['source']
        state = 'completed' if run['state'] in {'review', 'succeeded'} and result.get('complete') else 'failed' if run['state'] == 'failed' else 'partial'
        with self._connect() as connection:
            connection.execute("""INSERT OR IGNORE INTO memory_pin_agent_events
                (category_id,event_key,range_id,period_title,start_date,end_date,system_prompt,instructions,output,agent,model,status,created_at)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (pin['category_id'], 'bridge:' + run['id'], pin['id'], pin['title'], pin['start_date'], pin['end_date'],
                 snap['category_guidance'], pin['prompt'], result.get('summary', ''), run['agent'], result.get('model', ''), state, run['updated_at']))

    def save_range(
        self,
        *,
        range_id: int | None,
        category_id: int,
        start_date: str,
        end_date: str,
        note: str,
        title: str = "",
        prompt: str = "",
        execution_hour: int = 0,
        agent_enabled: bool | None = None,
    ) -> int:
        if type(execution_hour) is not int or not 0 <= execution_hour <= 23:
            raise ValueError('Choose an execution hour from 00 to 23 (Asia/Singapore).')
        if agent_enabled is not None and type(agent_enabled) is not bool:
            raise ValueError('Choose whether scheduled agent runs are enabled.')
        try:
            start = date.fromisoformat(start_date)
            end = date.fromisoformat(end_date)
        except ValueError as exc:
            raise ValueError("Choose valid start and end dates.") from exc
        if start > end:
            start, end = end, start
        title = title.strip()
        if not title or len(title) > 2000:
            raise ValueError("A title of 1 to 2,000 characters is required.")
        if len(prompt) > 20000:
            raise ValueError("Use 20,000 characters or fewer for a prompt.")
        note = note.strip()
        if len(note) > 2000:
            raise ValueError("Use 2,000 characters or fewer for a note.")
        now = datetime.now(timezone.utc).isoformat()
        try:
            with self._connect() as connection:
                exists = connection.execute(
                    "SELECT 1 FROM memory_pin_categories WHERE id=? AND archived_at IS NULL", (category_id,)
                ).fetchone()
                if not exists:
                    raise ValueError("Choose an existing category.")
                if range_id:
                    cursor = connection.execute(
                        """UPDATE memory_pin_ranges
                           SET category_id=?, start_date=?, end_date=?, note=?, title=?, prompt=?, updated_at=?, execution_hour=?, agent_enabled=COALESCE(?,agent_enabled)
                           WHERE id=?""",
                        (category_id, start.isoformat(), end.isoformat(), note, title, prompt, now, execution_hour, agent_enabled, range_id),
                    )
                    if not cursor.rowcount:
                        raise ValueError("That pinned range no longer exists.")
                else:
                    cursor = connection.execute(
                        """INSERT INTO memory_pin_ranges
                           (category_id, start_date, end_date, note, title, prompt, created_at, updated_at, execution_hour, agent_enabled)
                           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                        (category_id, start.isoformat(), end.isoformat(), note, title, prompt, now, now, execution_hour, bool(prompt.strip()) if agent_enabled is None else agent_enabled),
                    )
                return range_id or cursor.lastrowid
        except sqlite3.IntegrityError as exc:
            raise ValueError("The pinned range could not be saved.") from exc

    def delete_range(self, range_id: int) -> None:
        with self._connect() as connection:
            connection.execute("DELETE FROM memory_pin_ranges WHERE id=?", (range_id,))


@lru_cache(maxsize=1)
def get_memory_pin_store() -> MemoryPinStore:
    return MemoryPinStore(Path(get_settings().profile_store_path).expanduser().resolve())


def reset_memory_pin_store() -> None:
    get_memory_pin_store.cache_clear()
