"""Durable agent requests and append-only events, owned by one frontend host."""
from __future__ import annotations

import hashlib
import json
import sqlite3
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path


def now():
    return datetime.now(timezone.utc).isoformat()


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


class BridgeConflict(ValueError):
    pass


class AgentBridgeStore:
    def __init__(self, path: Path):
        self.path = path
        path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS agent_subscriptions (
                    source_key TEXT PRIMARY KEY, kind TEXT NOT NULL, source_id TEXT NOT NULL,
                    cadence TEXT NOT NULL, auto_complete INTEGER NOT NULL, updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS agent_requests (
                    id TEXT PRIMARY KEY, request_key TEXT NOT NULL UNIQUE, source_key TEXT NOT NULL,
                    state TEXT NOT NULL, snapshot TEXT NOT NULL, agent TEXT NOT NULL DEFAULT '',
                    lease_token TEXT NOT NULL DEFAULT '', lease_until TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
                    result TEXT NOT NULL DEFAULT '{}', delivery TEXT NOT NULL DEFAULT 'none',
                    applied INTEGER NOT NULL DEFAULT 0, expected_version INTEGER NOT NULL DEFAULT 0
                );
                CREATE UNIQUE INDEX IF NOT EXISTS agent_one_live_source ON agent_requests(source_key)
                    WHERE state IN ('queued','running','awaiting_input','review','accepting');
                CREATE TABLE IF NOT EXISTS agent_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT, run_id TEXT NOT NULL REFERENCES agent_requests(id),
                    event_key TEXT NOT NULL, kind TEXT NOT NULL, actor TEXT NOT NULL,
                    created_at TEXT NOT NULL, payload TEXT NOT NULL, UNIQUE(run_id,event_key)
                );
                CREATE TABLE IF NOT EXISTS agent_dispatch_state (
                    key TEXT PRIMARY KEY, value TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS agent_artifacts (
                    run_id TEXT NOT NULL REFERENCES agent_requests(id), name TEXT NOT NULL,
                    digest TEXT NOT NULL, size INTEGER NOT NULL,
                    PRIMARY KEY(run_id,name)
                );
            """)
            db.execute('BEGIN IMMEDIATE')
            index = db.execute("SELECT sql FROM sqlite_master WHERE name='agent_one_live_source'").fetchone()
            if index and 'awaiting_input' in index['sql']:
                db.execute('DROP INDEX agent_one_live_source')
                db.execute("CREATE UNIQUE INDEX agent_one_live_source ON agent_requests(source_key) WHERE state IN ('queued','running','review','accepting')")

    def connect(self):
        db = sqlite3.connect(self.path, timeout=15)
        db.row_factory = sqlite3.Row
        db.execute('PRAGMA foreign_keys=ON')
        return db

    @staticmethod
    def decode(row, *, private=False):
        result = dict(row)
        result['snapshot'] = json.loads(result['snapshot'])
        result['result'] = json.loads(result['result'])
        if not private:
            result.pop('lease_token', None)
        return result

    def get(self, run_id, *, private=False):
        with self.connect() as db:
            row = db.execute('SELECT * FROM agent_requests WHERE id=?', (run_id,)).fetchone()
        if not row:
            raise KeyError(run_id)
        return self.decode(row, private=private)

    def list(self, source_key=None, *, state=None, delivery=None, limit=100, oldest=False):
        with self.connect() as db:
            order = 'ASC' if oldest else 'DESC'
            rows = db.execute('SELECT * FROM agent_requests WHERE (? IS NULL OR source_key=?) AND (? IS NULL OR state=?) AND (? IS NULL OR delivery=?) ORDER BY created_at ' + order + ' LIMIT ?',
                              (source_key, source_key, state, state, delivery, delivery, limit)).fetchall()
        return [self.decode(row) for row in rows]

    def subscribe(self, kind, source_id, cadence, auto_complete):
        if cadence not in {'off', 'daily', 'after_period'} or type(auto_complete) is not bool:
            raise ValueError('Choose off, daily, or after_period and a completion policy.')
        if kind == 'actionable' and cadence == 'after_period':
            raise ValueError('After period is only available for pins.')
        with self.connect() as db:
            db.execute('INSERT INTO agent_subscriptions VALUES (?,?,?,?,?,?) ON CONFLICT(source_key) DO UPDATE SET cadence=excluded.cadence,auto_complete=excluded.auto_complete,updated_at=excluded.updated_at',
                       (f'{kind}:{source_id}', kind, str(source_id), cadence, int(auto_complete), now()))

    def subscriptions(self):
        with self.connect() as db:
            return [dict(row) for row in db.execute('SELECT * FROM agent_subscriptions ORDER BY source_key')]

    @staticmethod
    def event(db, run_id, key, kind, actor, payload):
        db.execute('INSERT INTO agent_events(run_id,event_key,kind,actor,created_at,payload) VALUES (?,?,?,?,?,?)',
                   (run_id, key, kind, actor, now(), json.dumps(payload, ensure_ascii=False)))

    def enqueue(self, snapshot, request_key, actor):
        if not isinstance(request_key, str) or not 1 <= len(request_key) <= 200:
            raise ValueError('A bounded request key is required.')
        source_key = snapshot['source_key']
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            previous = db.execute('SELECT * FROM agent_requests WHERE request_key=?', (request_key,)).fetchone()
            if previous:
                if previous['source_key'] != source_key:
                    raise BridgeConflict('Request key already belongs to another source.')
                return self.decode(previous)
            previous = db.execute("SELECT * FROM agent_requests WHERE source_key=? AND state IN ('queued','running','review','accepting')", (source_key,)).fetchone()
            if previous:
                return self.decode(previous)
            run_id, timestamp = uuid.uuid4().hex, now()
            db.execute('INSERT INTO agent_requests(id,request_key,source_key,state,snapshot,created_at,updated_at) VALUES (?,?,?,?,?,?,?)',
                       (run_id, request_key, source_key, 'queued', json.dumps(snapshot, ensure_ascii=False), timestamp, timestamp))
            self.event(db, run_id, 'queued', 'queued', actor, {'summary': 'Execution requested', 'instruction_hash': snapshot['instruction_hash']})
        return self.get(run_id)

    def claim(self, run_id, agent):
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            row = db.execute('SELECT * FROM agent_requests WHERE id=?', (run_id,)).fetchone()
            if not row or row['state'] != 'queued':
                raise BridgeConflict('This request is no longer queued.')
            token = uuid.uuid4().hex
            until = (datetime.now(timezone.utc) + timedelta(minutes=5)).isoformat()
            db.execute("UPDATE agent_requests SET state='running',agent=?,lease_token=?,lease_until=?,updated_at=? WHERE id=?", (agent, token, until, now(), run_id))
            self.event(db, run_id, 'claimed', 'running', agent, {'summary': 'Agent claimed this request.'})
        return self.get(run_id, private=True)

    def report(self, run_id, agent, token, event_key, kind, payload):
        if kind not in {'heartbeat', 'plan', 'progress', 'awaiting_input', 'succeeded', 'failed'}:
            raise ValueError('Unsupported agent event.')
        if not isinstance(event_key, str) or not 1 <= len(event_key) <= 160:
            raise ValueError('A bounded event key is required.')
        event_key = 'agent:' + event_key
        if not isinstance(payload, dict) or len(json.dumps(payload)) > 120000:
            raise ValueError('Event payload is too large or invalid.')
        if not isinstance(payload.get('model', ''), str) or len(payload.get('model', '')) > 200:
            raise ValueError('Model attribution must be text of at most 200 characters.')
        summary = payload.get('summary', '')
        if not isinstance(summary, str) or len(summary) > 100000 or (kind != 'heartbeat' and not summary.strip()):
            raise ValueError('An event summary is required (up to 100,000 characters).')
        evidence = payload.get('evidence', [])
        if not isinstance(evidence, list) or len(evidence) > 30 or any(not isinstance(ref, str) or len(ref) > 2000 for ref in evidence):
            raise ValueError('Evidence must be a list of up to 30 bounded references.')
        if kind == 'succeeded' and (not evidence or type(payload.get('complete')) is not bool):
            raise ValueError('Successful results require evidence and an explicit completion decision.')
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            row = db.execute('SELECT * FROM agent_requests WHERE id=?', (run_id,)).fetchone()
            if not row or row['agent'] != agent or not token or row['lease_token'] != token:
                raise BridgeConflict('This agent does not own the request.')
            previous = db.execute('SELECT kind,payload FROM agent_events WHERE run_id=? AND event_key=?', (run_id, event_key)).fetchone()
            if previous:
                if previous['kind'] != kind or json.loads(previous['payload']) != payload:
                    raise BridgeConflict('Event key already used for a different event.')
                return self.decode(row)
            if row['state'] != 'running' or row['lease_until'] < now():
                raise BridgeConflict('The execution lease is no longer active.')
            if kind == 'succeeded' and not db.execute("SELECT 1 FROM agent_events WHERE run_id=? AND kind='plan'", (run_id,)).fetchone():
                raise ValueError('Record the plan before submitting a result.')
            state = 'review' if kind == 'succeeded' else kind if kind in {'awaiting_input', 'failed'} else 'running'
            terminal = kind in {'succeeded', 'failed', 'awaiting_input'}
            until = (datetime.now(timezone.utc) + timedelta(minutes=5)).isoformat()
            if kind != 'heartbeat':
                self.event(db, run_id, event_key, kind, agent, payload)
            db.execute('UPDATE agent_requests SET state=?,lease_until=?,updated_at=?,result=?,delivery=? WHERE id=?',
                       (state, until, now(), json.dumps(payload) if terminal else row['result'], 'pending' if terminal else row['delivery'], run_id))
        return self.get(run_id)

    def owner_transition(self, run_id, state, actor, summary):
        if state not in {'cancelled', 'succeeded'}:
            raise ValueError('Unsupported owner decision.')
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            row = db.execute('SELECT * FROM agent_requests WHERE id=?', (run_id,)).fetchone()
            if not row:
                raise KeyError(run_id)
            if row['state'] == state:
                return self.decode(row)
            if state == 'succeeded' and row['state'] != 'accepting':
                raise BridgeConflict('Only a submitted result can be accepted.')
            if state == 'cancelled' and row['state'] not in {'queued', 'running', 'awaiting_input', 'review'}:
                raise BridgeConflict('This run already ended.')
            db.execute('UPDATE agent_requests SET state=?,lease_until=?,updated_at=? WHERE id=?', (state, '', now(), run_id))
            self.event(db, run_id, 'owner:' + state, state, actor, {'summary': summary})
        return self.get(run_id)

    def begin_accept(self, run_id, actor):
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            row = db.execute('SELECT * FROM agent_requests WHERE id=?', (run_id,)).fetchone()
            if not row:
                raise KeyError(run_id)
            if row['state'] not in {'review', 'accepting'}:
                raise BridgeConflict('Only a submitted result can be accepted.')
            if row['state'] == 'review':
                db.execute("UPDATE agent_requests SET state='accepting',updated_at=? WHERE id=?", (now(), run_id))
                self.event(db, run_id, 'approval:' + uuid.uuid4().hex, 'accepted', actor, {'summary': 'Result approved for application under the recorded completion policy.'})
        return self.get(run_id)

    def acceptance_failed(self, run_id):
        with self.connect() as db:
            db.execute("UPDATE agent_requests SET state='review' WHERE id=? AND state='accepting' AND applied=0", (run_id,))

    def expire(self):
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            for row in db.execute("SELECT id FROM agent_requests WHERE state='running' AND lease_until<?", (now(),)).fetchall():
                payload = {'summary': 'Agent heartbeat expired. Inspect the result before starting a new attempt.'}
                db.execute("UPDATE agent_requests SET state='failed',result=?,delivery='pending',updated_at=? WHERE id=?", (json.dumps(payload), now(), row['id']))
                self.event(db, row['id'], 'expired', 'failed', 'bridge', payload)

    def events(self, source_key):
        with self.connect() as db:
            rows = db.execute('SELECT e.* FROM agent_events e JOIN agent_requests r ON r.id=e.run_id WHERE r.source_key=? ORDER BY e.id DESC LIMIT 300', (source_key,)).fetchall()
        return [{**dict(row), 'payload': json.loads(row['payload'])} for row in rows]

    def mark_delivery(self, run_id, state):
        with self.connect() as db:
            db.execute('UPDATE agent_requests SET delivery=? WHERE id=?', (state, run_id))

    def mark_applied(self, run_id):
        with self.connect() as db:
            db.execute('UPDATE agent_requests SET applied=1 WHERE id=?', (run_id,))

    def set_version(self, run_id, version):
        with self.connect() as db:
            db.execute('UPDATE agent_requests SET expected_version=? WHERE id=?', (version, run_id))

    def dispatch_due(self, key, minutes):
        """Serialize competing scheduler ticks; persist the next discovery time."""
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            row = db.execute('SELECT value FROM agent_dispatch_state WHERE key=?', (key,)).fetchone()
            if row and (datetime.fromisoformat(row['value']) + timedelta(minutes=minutes)).isoformat() > now():
                return False
            db.execute('INSERT INTO agent_dispatch_state VALUES (?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value', (key, now()))
            return True

    def request_exists(self, key):
        with self.connect() as db:
            return bool(db.execute('SELECT 1 FROM agent_requests WHERE request_key=?', (key,)).fetchone())

    def notice_sent(self, key):
        with self.connect() as db:
            return bool(db.execute('SELECT 1 FROM agent_dispatch_state WHERE key=?', (key,)).fetchone())

    def mark_notice(self, key):
        with self.connect() as db:
            db.execute('INSERT OR IGNORE INTO agent_dispatch_state VALUES (?,?)', (key, now()))

    def artifacts(self, run_id):
        with self.connect() as db:
            return [dict(row) for row in db.execute('SELECT name,digest,size FROM agent_artifacts WHERE run_id=? ORDER BY name', (run_id,))]
