"""Private, owner-scoped Memory Signal categories and annotated date ranges."""

from __future__ import annotations

import sqlite3
from dataclasses import asdict, dataclass
from datetime import date, datetime, timezone
from functools import lru_cache
from pathlib import Path

from config import get_settings


PIN_COLORS = (
    "#f59e0b",  # amber
    "#f97316",  # orange
    "#f43f5e",  # rose
    "#d946ef",  # fuchsia
    "#8b5cf6",  # violet
    "#3b82f6",  # blue
    "#14b8a6",  # teal
    "#84cc16",  # lime
    "#e5e7eb",  # light grey
    "#9ca3af",  # medium grey
    "#64748b",  # slate
    "#475569",  # charcoal
)


@dataclass(frozen=True)
class PinCategory:
    id: int
    name: str
    color: str


@dataclass(frozen=True)
class PinRange:
    id: int
    category_id: int
    start_date: str
    end_date: str
    note: str
    updated_at: str


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
                "SELECT id, name, color FROM memory_pin_categories ORDER BY id"
            ).fetchall()
            ranges = connection.execute(
                """SELECT id, category_id, start_date, end_date, note, updated_at
                   FROM memory_pin_ranges ORDER BY start_date, end_date, id"""
            ).fetchall()
        return {
            "categories": [asdict(PinCategory(**dict(row))) for row in categories],
            "ranges": [asdict(PinRange(**dict(row))) for row in ranges],
            "palette": list(PIN_COLORS),
        }

    def save_category(self, *, category_id: int | None, name: str, color: str) -> None:
        name = name.strip()
        if not name or len(name) > 60:
            raise ValueError("Category names must contain 1 to 60 characters.")
        if color not in PIN_COLORS:
            raise ValueError("Choose one of the twelve Memory Signal colors.")
        now = datetime.now(timezone.utc).isoformat()
        try:
            with self._connect() as connection:
                if category_id:
                    cursor = connection.execute(
                        """UPDATE memory_pin_categories SET name=?, color=?, updated_at=?
                           WHERE id=?""",
                        (name, color, now, category_id),
                    )
                    if not cursor.rowcount:
                        raise ValueError("That category no longer exists.")
                else:
                    connection.execute(
                        """INSERT INTO memory_pin_categories(name, color, created_at, updated_at)
                           VALUES (?, ?, ?, ?)""",
                        (name, color, now, now),
                    )
        except sqlite3.IntegrityError as exc:
            raise ValueError("Category names must be unique.") from exc

    def delete_category(self, category_id: int) -> None:
        with self._connect() as connection:
            connection.execute("DELETE FROM memory_pin_categories WHERE id=?", (category_id,))

    def save_range(
        self,
        *,
        range_id: int | None,
        category_id: int,
        start_date: str,
        end_date: str,
        note: str,
    ) -> None:
        try:
            start = date.fromisoformat(start_date)
            end = date.fromisoformat(end_date)
        except ValueError as exc:
            raise ValueError("Choose valid start and end dates.") from exc
        if start > end:
            start, end = end, start
        note = note.strip()
        if len(note) > 2000:
            raise ValueError("Use 2,000 characters or fewer for a note.")
        now = datetime.now(timezone.utc).isoformat()
        try:
            with self._connect() as connection:
                exists = connection.execute(
                    "SELECT 1 FROM memory_pin_categories WHERE id=?", (category_id,)
                ).fetchone()
                if not exists:
                    raise ValueError("Choose an existing category.")
                if range_id:
                    cursor = connection.execute(
                        """UPDATE memory_pin_ranges
                           SET category_id=?, start_date=?, end_date=?, note=?, updated_at=?
                           WHERE id=?""",
                        (category_id, start.isoformat(), end.isoformat(), note, now, range_id),
                    )
                    if not cursor.rowcount:
                        raise ValueError("That pinned range no longer exists.")
                else:
                    connection.execute(
                        """INSERT INTO memory_pin_ranges
                           (category_id, start_date, end_date, note, created_at, updated_at)
                           VALUES (?, ?, ?, ?, ?, ?)""",
                        (category_id, start.isoformat(), end.isoformat(), note, now, now),
                    )
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
