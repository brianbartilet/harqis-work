"""Copy legacy pinned-date Notes into Title, retaining Notes.

Preview: python scripts/agents/hfl/migrate_pin_titles.py --database /path/to/profile.sqlite3
Apply:   python scripts/agents/hfl/migrate_pin_titles.py --database /path/to/profile.sqlite3 --apply
Uses only the standard library; does not start the app or load its stores.
"""

from __future__ import annotations

import argparse
from contextlib import closing
from datetime import datetime, timezone
import json
from pathlib import Path
import sqlite3
import tempfile


def migrate(database: Path, *, apply: bool = False) -> dict:
    database = database.expanduser().resolve(strict=True)
    if not database.is_file():
        raise ValueError("Database must be an existing SQLite file.")
    uri = database.as_uri()
    with closing(sqlite3.connect(uri + ("?mode=rw" if apply else "?mode=ro"), uri=True)) as connection:
        try:
            connection.execute("BEGIN IMMEDIATE" if apply else "BEGIN")
            columns = [row[1] for row in connection.execute("PRAGMA table_info(memory_pin_ranges)")]
            required = {"id", "category_id", "start_date", "end_date", "note", "created_at", "updated_at"}
            if not required.issubset(columns):
                raise ValueError("Expected memory_pin_ranges schema not found. Use the profile database, not the timeline database.")
            count, blank = connection.execute(
                "SELECT count(*), coalesce(sum(trim(note)=''), 0) FROM memory_pin_ranges"
            ).fetchone()
            result = {"database": str(database), "pins": count}
            if "title" in columns:
                return {**result, "status": "already_migrated", "changed": 0}
            result.update(notes_to_title=count - blank, untitled=blank)
            if not apply:
                return {**result, "status": "dry_run", "changed": 0}

            # A second reader backs up the committed snapshot while the first
            # connection holds the write reservation. SQLite backup includes WAL.
            stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
            with tempfile.NamedTemporaryFile(
                prefix=f"{database.name}.before-pin-titles-{stamp}-",
                suffix=".sqlite3", dir=database.parent, delete=False,
            ) as backup_file:
                backup = Path(backup_file.name)
            with closing(sqlite3.connect(uri + "?mode=ro", uri=True)) as source:
                with closing(sqlite3.connect(backup)) as destination:
                    source.backup(destination)
                    if destination.execute("PRAGMA quick_check").fetchall() != [("ok",)]:
                        raise sqlite3.DatabaseError("Backup integrity check failed; migration aborted.")

            original = connection.execute("SELECT * FROM memory_pin_ranges ORDER BY id").fetchall()
            connection.execute("ALTER TABLE memory_pin_ranges ADD COLUMN title TEXT NOT NULL DEFAULT ''")
            connection.execute("UPDATE memory_pin_ranges SET title=CASE WHEN trim(note)='' THEN 'Untitled pin' ELSE note END")
            migrated = connection.execute("SELECT * FROM memory_pin_ranges ORDER BY id").fetchall()
            if [row[:-1] for row in migrated] != original:
                raise sqlite3.IntegrityError("Original pin fields changed; migration rolled back.")
            connection.commit()
            return {**result, "status": "applied", "changed": count, "backup": str(backup)}
        finally:
            connection.rollback()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", required=True, type=Path, help="Existing PROFILE_STORE_PATH SQLite database")
    parser.add_argument("--apply", action="store_true", help="Back up and apply; default is a read-only preview")
    args = parser.parse_args()
    try:
        print(json.dumps(migrate(args.database, apply=args.apply), indent=2))
    except (OSError, ValueError, sqlite3.Error) as exc:
        parser.exit(1, f"Migration failed: {exc}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
