"""Versioned fleet definitions and a durable audit outbox; no runtime credentials."""
import json
import sqlite3
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path


def now():
    return datetime.now(timezone.utc).isoformat()


class FleetConflict(ValueError):
    pass


class AgentFleetStore:
    def __init__(self, path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as db:
            db.executescript('''
                CREATE TABLE IF NOT EXISTS fleet_work_state (user TEXT PRIMARY KEY, version INTEGER NOT NULL, payload TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS fleet_profile_sources (id TEXT PRIMARY KEY, version INTEGER NOT NULL, payload TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS fleet_profile_index (source TEXT NOT NULL, id TEXT NOT NULL, payload TEXT NOT NULL, PRIMARY KEY(source,id));
                CREATE TABLE IF NOT EXISTS fleet_profile_cache (hash TEXT PRIMARY KEY, content BLOB NOT NULL, accessed REAL NOT NULL);
                CREATE TABLE IF NOT EXISTS fleet_receipt_versions (user TEXT PRIMARY KEY, version INTEGER NOT NULL);
                CREATE TABLE IF NOT EXISTS fleet_read_receipts (user TEXT NOT NULL, item_key TEXT NOT NULL, reviewed INTEGER NOT NULL, PRIMARY KEY(user,item_key));
                CREATE TABLE IF NOT EXISTS fleet_agents (
                    id TEXT PRIMARY KEY, version INTEGER NOT NULL, payload TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS fleet_assets (
                    id TEXT PRIMARY KEY, name TEXT NOT NULL, media_type TEXT NOT NULL, content BLOB NOT NULL);
                CREATE TABLE IF NOT EXISTS fleet_events (
                    id TEXT PRIMARY KEY, agent_id TEXT NOT NULL, created TEXT NOT NULL,
                    payload TEXT NOT NULL, delivered INTEGER NOT NULL DEFAULT 0);
                CREATE TABLE IF NOT EXISTS fleet_chat (
                    user TEXT NOT NULL, request_id TEXT NOT NULL, message TEXT NOT NULL,
                    created TEXT NOT NULL, action_id TEXT NOT NULL DEFAULT '', run_id TEXT NOT NULL DEFAULT '',
                    PRIMARY KEY(user,request_id));
                CREATE TABLE IF NOT EXISTS fleet_briefings (
                    user TEXT PRIMARY KEY, version INTEGER NOT NULL, payload TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS fleet_briefing_deliveries (
                    user TEXT NOT NULL, request_id TEXT NOT NULL, scheduled_date TEXT NOT NULL,
                    payload TEXT NOT NULL, PRIMARY KEY(user,request_id));
                CREATE TABLE IF NOT EXISTS fleet_assistant (
                    user TEXT NOT NULL, id TEXT NOT NULL, kind TEXT NOT NULL,
                    payload TEXT NOT NULL, PRIMARY KEY(user,id));
                CREATE TABLE IF NOT EXISTS fleet_objects (
                    user TEXT NOT NULL, id TEXT NOT NULL, payload TEXT NOT NULL,
                    PRIMARY KEY(user,id));
            ''')

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.path, timeout=30)
        db.row_factory = sqlite3.Row
        try:
            with db:
                yield db
        finally:
            db.close()

    def list(self):
        with self.connect() as db:
            return [json.loads(r['payload']) for r in db.execute('SELECT payload FROM fleet_agents ORDER BY id')]

    def get(self, identity):
        with self.connect() as db:
            row = db.execute('SELECT payload FROM fleet_agents WHERE id=?', (identity,)).fetchone()
        if not row:
            raise KeyError(identity)
        return json.loads(row[0])

    def save(self, data, *, identity=None, version=None, seed=False):
        identity = identity or 'agent-' + uuid.uuid4().hex
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            old = db.execute('SELECT * FROM fleet_agents WHERE id=?', (identity,)).fetchone()
            if old and seed:
                return json.loads(old['payload'])
            if old and (type(version) is not int or old['version'] != version):
                raise FleetConflict('Agent changed. Reload before saving.')
            if not old and version is not None:
                raise KeyError(identity)
            stamp = now()
            item = {**data, 'id': identity, 'version': old['version'] + 1 if old else 1,
                    'created_at': json.loads(old['payload'])['created_at'] if old else stamp, 'updated_at': stamp}
            db.execute('INSERT INTO fleet_agents VALUES (?,?,?) ON CONFLICT(id) DO UPDATE SET version=excluded.version,payload=excluded.payload',
                       (identity, item['version'], json.dumps(item)))
            # The version and its receipt commit together. Delivery is retryable.
            self.event(identity + ':' + str(item['version']), identity,
                       {'kind': 'configuration', 'name': item['name'], 'version': item['version'],
                        'active': item.get('active', True)}, db=db)
        return item

    def event(self, key, agent_id, data, db=None):
        if db is None:
            with self.connect() as connection:
                return self.event(key, agent_id, data, db=connection)
        db.execute('INSERT OR IGNORE INTO fleet_events(id,agent_id,created,payload) VALUES (?,?,?,?)',
                   (key, agent_id, now(), json.dumps(data)))

    def events(self, agent_id=None, pending=False):
        with self.connect() as db:
            return [{**dict(r), 'payload': json.loads(r['payload'])} for r in db.execute(
                'SELECT * FROM fleet_events WHERE (? IS NULL OR agent_id=?) AND (?=0 OR delivered=0) ORDER BY created DESC LIMIT 100',
                (agent_id, agent_id, int(pending)))]

    def asset(self, identity):
        with self.connect() as db:
            row = db.execute('SELECT * FROM fleet_assets WHERE id=?', (identity,)).fetchone()
        if row is None:
            raise KeyError(identity)
        return dict(row)

    def put_asset(self, name, media_type, content):
        import hashlib
        identity = hashlib.sha256(content).hexdigest()
        with self.connect() as db:
            db.execute('INSERT OR IGNORE INTO fleet_assets VALUES (?,?,?,?)', (identity, name, media_type, content))
        return identity
