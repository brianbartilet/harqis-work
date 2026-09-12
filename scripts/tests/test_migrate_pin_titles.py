"""Synthetic SQLite checks; never reads the configured profile database."""

from contextlib import closing
import importlib.util
from pathlib import Path
import sqlite3
import tempfile
import unittest

SCRIPT = Path(__file__).resolve().parents[1] / "agents/hfl/migrate_pin_titles.py"
spec = importlib.util.spec_from_file_location("migrate_pin_titles", SCRIPT)
migration = importlib.util.module_from_spec(spec)
spec.loader.exec_module(migration)


class PinTitleMigrationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.database = Path(self.temp.name) / "profile.sqlite3"
        with closing(sqlite3.connect(self.database)) as db, db:
            db.execute("CREATE TABLE memory_pin_ranges (id INTEGER PRIMARY KEY, category_id INTEGER, start_date TEXT, end_date TEXT, note TEXT NOT NULL, created_at TEXT, updated_at TEXT)")
            db.executemany("INSERT INTO memory_pin_ranges VALUES (?, 4, '2024-01-01', '2024-01-28', ?, 'created', 'updated')", [(1, ' SG Peon Start '), (2, ''), (3, '   '), (4, '# Long note\n' * 180)])

    def rows(self, path=None):
        with closing(sqlite3.connect(path or self.database)) as db:
            return db.execute("SELECT * FROM memory_pin_ranges ORDER BY id").fetchall()

    def test_preview_is_read_only(self):
        before = self.database.read_bytes()
        result = migration.migrate(self.database)
        self.assertEqual((result['status'], result['notes_to_title'], result['untitled']), ('dry_run', 2, 2))
        self.assertEqual(self.database.read_bytes(), before)
        self.assertEqual(len(list(Path(self.temp.name).iterdir())), 1)

    def test_apply_backup_preservation_and_rerun(self):
        before = self.rows()
        result = migration.migrate(self.database, apply=True)
        self.assertEqual(self.rows(result['backup']), before)
        after = self.rows()
        self.assertEqual([row[:-1] for row in after], before)
        self.assertEqual([row[-1] for row in after], [' SG Peon Start ', 'Untitled pin', 'Untitled pin', '# Long note\n' * 180])
        with closing(sqlite3.connect(self.database)) as db, db:
            db.execute("UPDATE memory_pin_ranges SET title='Edited title' WHERE id=1")
        self.assertEqual(migration.migrate(self.database, apply=True)['status'], 'already_migrated')
        self.assertEqual(self.rows()[0][-1], 'Edited title')
        self.assertEqual(len(list(Path(self.temp.name).glob('*.sqlite3'))), 2)

    def test_missing_or_wrong_database_is_not_created_or_changed(self):
        missing = Path(self.temp.name) / 'missing.sqlite3'
        with self.assertRaises(FileNotFoundError):
            migration.migrate(missing, apply=True)
        self.assertFalse(missing.exists())
        with closing(sqlite3.connect(self.database)) as db, db:
            db.execute('DROP TABLE memory_pin_ranges')
        with self.assertRaises(ValueError):
            migration.migrate(self.database, apply=True)

    def test_wal_backup_includes_committed_notes(self):
        with closing(sqlite3.connect(self.database)) as writer, writer:
            writer.execute('PRAGMA journal_mode=WAL')
            writer.execute("UPDATE memory_pin_ranges SET note='WAL note' WHERE id=1")
            writer.commit()
            result = migration.migrate(self.database, apply=True)
            self.assertEqual(self.rows(result['backup'])[0][4], 'WAL note')
            self.assertEqual(self.rows()[0][-1], 'WAL note')


if __name__ == '__main__':
    unittest.main()
