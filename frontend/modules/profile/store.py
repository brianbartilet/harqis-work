"""SQLite persistence for the single global owner profile."""

from __future__ import annotations

import sqlite3
from functools import lru_cache
from pathlib import Path

from config import get_settings
from modules.profile.models import OwnerProfile


_SCHEMA = """
CREATE TABLE IF NOT EXISTS owner_profile (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    first_name TEXT NOT NULL DEFAULT '',
    last_name TEXT NOT NULL DEFAULT '',
    nickname TEXT NOT NULL DEFAULT '',
    birthdate TEXT NOT NULL DEFAULT '',
    location TEXT NOT NULL DEFAULT '',
    phone TEXT NOT NULL DEFAULT '',
    bio TEXT NOT NULL DEFAULT '',
    email TEXT NOT NULL DEFAULT '',
    linkedin_url TEXT NOT NULL DEFAULT '',
    github_url TEXT NOT NULL DEFAULT '',
    website_url TEXT NOT NULL DEFAULT '',
    instagram_url TEXT NOT NULL DEFAULT '',
    avatar BLOB NOT NULL DEFAULT X'',
    avatar_content_type TEXT NOT NULL DEFAULT '',
    secret_pin_hash TEXT NOT NULL DEFAULT '',
    secret_tags TEXT NOT NULL DEFAULT '',
    updated_at TEXT NOT NULL DEFAULT ''
);
"""


class ProfileStore:
    def __init__(self, path: Path):
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as connection:
            connection.executescript(_SCHEMA)
            columns = {
                row["name"] for row in connection.execute("PRAGMA table_info(owner_profile)")
            }
            for name in ("secret_pin_hash", "secret_tags", "birthdate"):
                if name not in columns:
                    connection.execute(
                        f"ALTER TABLE owner_profile ADD COLUMN {name} TEXT NOT NULL DEFAULT ''"
                    )

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path)
        connection.row_factory = sqlite3.Row
        return connection

    def get(self) -> OwnerProfile:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM owner_profile WHERE id=1"
            ).fetchone()
        if not row:
            return OwnerProfile()
        return OwnerProfile(
            **{
                field: row[field]
                for field in OwnerProfile.__dataclass_fields__
            }
        )

    def save(self, profile: OwnerProfile) -> OwnerProfile:
        fields = tuple(OwnerProfile.__dataclass_fields__)
        columns = ", ".join(fields)
        placeholders = ", ".join("?" for _ in fields)
        updates = ", ".join(f"{field}=excluded.{field}" for field in fields)
        values = tuple(getattr(profile, field) for field in fields)
        with self._connect() as connection:
            connection.execute(
                f"""
                INSERT INTO owner_profile(id, {columns})
                VALUES (1, {placeholders})
                ON CONFLICT(id) DO UPDATE SET {updates}
                """,
                values,
            )
        return profile


@lru_cache(maxsize=1)
def get_profile_store() -> ProfileStore:
    return ProfileStore(Path(get_settings().profile_store_path).expanduser().resolve())


def reset_profile_store() -> None:
    get_profile_store.cache_clear()
