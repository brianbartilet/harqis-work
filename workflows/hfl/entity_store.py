"""Rebuildable entity metadata, reversible identity decisions, and durable work intent."""
from __future__ import annotations

import hashlib
import json
import os
import sqlite3
from contextlib import contextmanager
from pathlib import Path


VERSION = 'corpus-entities-v1'


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


class EntityStore:
    def __init__(self, path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.connection() as db:
            db.executescript('''
                CREATE TABLE IF NOT EXISTS enrichment(id TEXT PRIMARY KEY, hash TEXT, version TEXT, mentions TEXT);
                CREATE TABLE IF NOT EXISTS decisions(id INTEGER PRIMARY KEY AUTOINCREMENT, alias TEXT,
                    canonical TEXT, reason TEXT, active INTEGER DEFAULT 1, created TEXT DEFAULT CURRENT_TIMESTAMP);
                CREATE TABLE IF NOT EXISTS pending(id TEXT PRIMARY KEY, revision TEXT, queued_at REAL DEFAULT 0);
                CREATE TABLE IF NOT EXISTS profiles(id TEXT PRIMARY KEY, kind TEXT NOT NULL,
                    data TEXT NOT NULL, updated TEXT DEFAULT CURRENT_TIMESTAMP);
                CREATE TABLE IF NOT EXISTS state(key TEXT PRIMARY KEY, value TEXT);
            ''')
            if 'queued_at' not in {r[1] for r in db.execute('PRAGMA table_info(pending)')}:
                db.execute('ALTER TABLE pending ADD COLUMN queued_at REAL DEFAULT 0')

    @contextmanager
    def connection(self):
        db = sqlite3.connect(self.path, timeout=30)
        db.row_factory = sqlite3.Row
        try:
            with db:
                yield db
        finally:
            db.close()

    def legacy_id(self, locator):
        return 'legacy-' + hashlib.sha256(locator.encode()).hexdigest()[:32]

    def records(self):
        with self.connection() as db:
            return {r['id']: {**dict(r), 'mentions': json.loads(r['mentions'])}
                    for r in db.execute('SELECT * FROM enrichment')}

    def save(self, identity, content_hash, mentions, version=VERSION):
        with self.connection() as db:
            db.execute('INSERT OR REPLACE INTO enrichment VALUES (?,?,?,?)',
                       (identity, content_hash, version, json.dumps(mentions)))

    def prune(self, current_ids):
        with self.connection() as db:
            old = {r[0] for r in db.execute('SELECT id FROM enrichment')}
            removed = old - set(current_ids)
            db.executemany('DELETE FROM enrichment WHERE id=?', [(i,) for i in removed])
        return len(removed)

    def decisions(self):
        with self.connection() as db:
            return [dict(row) for row in db.execute('SELECT * FROM decisions ORDER BY id')]

    def resolve(self, identity):
        aliases = {d['alias']: d['canonical'] for d in self.decisions() if d['active']}
        seen = set()
        while identity in aliases and identity not in seen:
            seen.add(identity)
            identity = aliases[identity]
        return identity

    def merge(self, alias, canonical, reason):
        if alias == canonical or self.resolve(canonical) == alias:
            raise ValueError('Identity merge would form a cycle')
        with self.connection() as db:
            db.execute('UPDATE decisions SET active=0 WHERE alias=?', (alias,))
            row = db.execute('INSERT INTO decisions(alias,canonical,reason) VALUES (?,?,?)',
                             (alias, canonical, reason))
            return row.lastrowid

    def undo(self, decision_id):
        with self.connection() as db:
            db.execute('UPDATE decisions SET active=0 WHERE id=?', (decision_id,))

    def profiles(self):
        with self.connection() as db:
            return {r['id']: {**json.loads(r['data']), 'id': r['id'], 'kind': r['kind'],
                              'updated': r['updated']}
                    for r in db.execute('SELECT * FROM profiles')}

    def save_profile(self, identity, kind, data):
        # Curated data is never pruned or overwritten by enrichment.
        with self.connection() as db:
            db.execute("INSERT INTO profiles(id,kind,data) VALUES (?,?,?) ON CONFLICT(id) "
                       "DO UPDATE SET data=excluded.data, updated=CURRENT_TIMESTAMP",
                       (identity, kind, json.dumps(data)))

    def state(self, key, value=None):
        with self.connection() as db:
            if value is not None:
                db.execute('INSERT OR REPLACE INTO state VALUES (?,?)', (key, json.dumps(value)))
            row = db.execute('SELECT value FROM state WHERE key=?', (key,)).fetchone()
            return json.loads(row[0]) if row else None


def get_store():
    path = os.environ.get('HARQIS_ENTITIES_DB')
    if not path:
        raise ValueError('HARQIS_ENTITIES_DB must identify a host-local derived store')
    return EntityStore(path)
