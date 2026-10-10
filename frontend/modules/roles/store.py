"""Versioned owner data; every edit keeps a reviewable prior revision."""
import json
import sqlite3
from datetime import datetime, timezone
from uuid import uuid4

from fastapi import HTTPException
from modules.profile.store import get_profile_store


def now():
    return datetime.now(timezone.utc).isoformat()


def connection():
    db = sqlite3.connect(get_profile_store().path, timeout=30)
    db.row_factory = sqlite3.Row
    db.executescript('''
        CREATE TABLE IF NOT EXISTS persona_roles(id TEXT PRIMARY KEY, revision INTEGER NOT NULL, payload TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS persona_history(id TEXT NOT NULL, revision INTEGER NOT NULL, payload TEXT NOT NULL, PRIMARY KEY(id, revision));
        CREATE TABLE IF NOT EXISTS persona_runs(id TEXT PRIMARY KEY, payload TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS persona_seen(role_id TEXT NOT NULL, evidence_id TEXT NOT NULL, digest TEXT NOT NULL, PRIMARY KEY(role_id,evidence_id));
    ''')
    return db


def listing():
    with connection() as db:
        return [json.loads(row[0]) for row in db.execute('SELECT payload FROM persona_roles ORDER BY id')]


def get(identity):
    with connection() as db:
        row = db.execute('SELECT payload FROM persona_roles WHERE id=?', (identity,)).fetchone()
    if row is None:
        raise HTTPException(404, 'Facet not found.')
    return json.loads(row[0])


def history(identity):
    get(identity)
    with connection() as db:
        return [json.loads(row[0]) for row in db.execute('SELECT payload FROM persona_history WHERE id=? ORDER BY revision DESC', (identity,))]


def save(identity, revision, changes, *, checkpoints=None):
    with connection() as db:
        db.execute('BEGIN IMMEDIATE')
        row = db.execute('SELECT payload FROM persona_roles WHERE id=?', (identity,)).fetchone() if identity else None
        if identity and row is None:
            raise HTTPException(404, 'Facet not found.')
        old = json.loads(row[0]) if row else {'id': uuid4().hex, 'revision': 0, 'journal': [], 'files': [], 'created_at': now()}
        if old['revision'] != revision:
            raise HTTPException(409, 'This facet changed. Reload and review before saving.')
        value = old
        if changes or not row:
            value = {**old, **changes, 'id': old['id'], 'revision': revision + 1, 'updated_at': now()}
            encoded = json.dumps(value)
            db.execute('INSERT INTO persona_roles VALUES(?,?,?) ON CONFLICT(id) DO UPDATE SET revision=excluded.revision,payload=excluded.payload', (value['id'], value['revision'], encoded))
            db.execute('INSERT INTO persona_history VALUES(?,?,?)', (value['id'], value['revision'], encoded))
        if checkpoints:
            db.executemany('INSERT INTO persona_seen VALUES(?,?,?) ON CONFLICT(role_id,evidence_id) DO UPDATE SET digest=excluded.digest',
                           [(value['id'], evidence_id, digest) for evidence_id, digest in checkpoints])
    return value


def attachment_store():
    from modules.hfl_corpus.attachments import AttachmentStore
    return AttachmentStore(get_profile_store().path)


def runs():
    with connection() as db:
        return [json.loads(r[0]) for r in db.execute('SELECT payload FROM persona_runs ORDER BY rowid DESC LIMIT 50')]


def record_run(value):
    with connection() as db:
        db.execute('INSERT INTO persona_runs VALUES(?,?) ON CONFLICT(id) DO UPDATE SET payload=excluded.payload', (value['id'], json.dumps(value)))
