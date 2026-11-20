"""Persistent native terminals and configuration, alongside the existing run queue."""
from __future__ import annotations

import json
import uuid
from datetime import datetime, timedelta, timezone

from workflows.hfl.agent_bridge_store import AgentBridgeStore, BridgeConflict, now
from workflows.hfl.terminal_events import notify


class ActionAgentStore(AgentBridgeStore):
    def __init__(self, path):
        super().__init__(path)
        with self.connect() as db:
            db.executescript('''
                CREATE TABLE IF NOT EXISTS action_agent_configs (
                    key TEXT PRIMARY KEY, value TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS action_agent_sessions (
                    id TEXT PRIMARY KEY, source_id TEXT NOT NULL, state TEXT NOT NULL,
                    settings TEXT NOT NULL, saved INTEGER NOT NULL DEFAULT 0,
                    title TEXT NOT NULL DEFAULT '', native_id TEXT NOT NULL DEFAULT '',
                    worker TEXT NOT NULL DEFAULT '', token TEXT NOT NULL DEFAULT '',
                    heartbeat TEXT NOT NULL, activity TEXT NOT NULL, created TEXT NOT NULL,
                    error TEXT NOT NULL DEFAULT '', cols INTEGER NOT NULL DEFAULT 100,
                    rows INTEGER NOT NULL DEFAULT 30, closed INTEGER NOT NULL DEFAULT 0);
                CREATE UNIQUE INDEX IF NOT EXISTS action_agent_one_terminal
                    ON action_agent_sessions(source_id) WHERE state IN ('queued','starting','idle','waiting','running');
                CREATE TABLE IF NOT EXISTS action_agent_io (
                    seq INTEGER PRIMARY KEY AUTOINCREMENT, session TEXT NOT NULL,
                    direction TEXT NOT NULL, request_key TEXT NOT NULL, data TEXT NOT NULL,
                    UNIQUE(session,direction,request_key));
                CREATE INDEX IF NOT EXISTS action_agent_io_replay ON action_agent_io(session,seq);
                CREATE TABLE IF NOT EXISTS action_agent_files (
                    session TEXT NOT NULL, name TEXT NOT NULL, digest TEXT NOT NULL,
                    PRIMARY KEY(session,name,digest));
                CREATE TABLE IF NOT EXISTS action_terminal_hosts (
                    host TEXT PRIMARY KEY, updated TEXT NOT NULL, capabilities TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS terminal_promotions (
                    session TEXT PRIMARY KEY, payload TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS terminal_locks (
                    key TEXT PRIMARY KEY, token TEXT NOT NULL, expires TEXT NOT NULL);
            ''')
            db.execute('BEGIN IMMEDIATE')
            columns = {r['name'] for r in db.execute('PRAGMA table_info(action_agent_sessions)')}
            for column in ('owner', 'fleet_id', 'action_id', 'restored_from'):
                if column not in columns:
                    db.execute(f"ALTER TABLE action_agent_sessions ADD COLUMN {column} TEXT NOT NULL DEFAULT ''")

    def lock(self, key, token, seconds=180):
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            db.execute('DELETE FROM terminal_locks WHERE expires<?', (now(),))
            return db.execute('INSERT OR IGNORE INTO terminal_locks VALUES (?,?,?)',
                              (key, token, (datetime.now(timezone.utc) + timedelta(seconds=seconds)).isoformat())).rowcount == 1

    def unlock(self, key, token):
        with self.connect() as db:
            db.execute('DELETE FROM terminal_locks WHERE key=? AND token=?', (key, token))

    def configs(self):
        with self.connect() as db:
            return {r['key']: json.loads(r['value']) for r in db.execute('SELECT * FROM action_agent_configs')}

    def advertise(self, host, capabilities):
        with self.connect() as db:
            db.execute('INSERT INTO action_terminal_hosts VALUES (?,?,?) ON CONFLICT(host) DO UPDATE SET updated=excluded.updated,capabilities=excluded.capabilities',
                       (host, now(), json.dumps(capabilities)))

    def hosts(self):
        cutoff = (datetime.now(timezone.utc) - timedelta(seconds=90)).isoformat()
        with self.connect() as db:
            return [{'host': r['host'], 'runtimes': json.loads(r['capabilities'])} for r in db.execute('SELECT * FROM action_terminal_hosts WHERE updated>?', (cutoff,))]

    def configure(self, key, value):
        with self.connect() as db:
            db.execute('INSERT INTO action_agent_configs VALUES (?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value',
                       (key, json.dumps(value)))

    @staticmethod
    def session_decode(row, private=False):
        data = dict(row)
        data['settings'] = json.loads(data['settings'])
        if not private:
            data.pop('token', None)
        return data

    def session(self, identity, private=False):
        with self.connect() as db:
            row = db.execute('SELECT * FROM action_agent_sessions WHERE id=?', (identity,)).fetchone()
        if row is None:
            raise KeyError(identity)
        return self.session_decode(row, private)

    def sessions(self, source_id=None):
        with self.connect() as db:
            rows = db.execute('SELECT * FROM action_agent_sessions WHERE (? IS NULL OR source_id=? OR action_id=?) ORDER BY created DESC',
                              (source_id, source_id, source_id)).fetchall()
        return [self.session_decode(row) for row in rows]

    def start_session(self, source_id, settings, title, restore=None, *, owner='', fleet_id=''):
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            live = db.execute("SELECT * FROM action_agent_sessions WHERE (source_id=? OR action_id=?) AND state IN ('queued','starting','idle','waiting','running')", (source_id, source_id)).fetchone()
            if live:
                return self.session_decode(live)
            native = ''
            action_id = ''
            if restore:
                previous = db.execute('SELECT * FROM action_agent_sessions WHERE id=? AND (source_id=? OR action_id=?)', (restore, source_id, source_id)).fetchone()
                if not previous or not previous['native_id']:
                    raise BridgeConflict('This session has no native context to restore. Its transcript remains available.')
                native = previous['native_id']
                # Native sessions belong to their original host and Hermes profile.
                original = json.loads(previous['settings'])
                for key in ('hermes_profile', 'agent_host', 'terminal_runtime'):
                    settings[key] = original.get(key, '')
                settings['agent_host'] = previous['worker'] or settings['agent_host']
                source_id, owner, fleet_id, action_id = previous['source_id'], previous['owner'], previous['fleet_id'], previous['action_id']
                if db.execute("SELECT 1 FROM action_agent_sessions WHERE source_id=? AND state IN ('queued','starting','idle','waiting','running')", (source_id,)).fetchone():
                    raise BridgeConflict('End the agent\'s other live session before restoring this Action session.')
            identity, timestamp = uuid.uuid4().hex, now()
            db.execute('INSERT INTO action_agent_sessions(id,source_id,state,settings,title,native_id,heartbeat,activity,created) VALUES (?,?,?,?,?,?,?,?,?)',
                       (identity, source_id, 'queued', json.dumps(settings), title[:200], native, timestamp, timestamp, timestamp))
            db.execute('UPDATE action_agent_sessions SET owner=?,fleet_id=?,action_id=?,restored_from=? WHERE id=?', (owner, fleet_id, action_id, restore or '', identity))
        return self.session(identity)

    def edit_session(self, identity, **fields):
        if not fields or set(fields) - {'saved','closed','cols','rows','title'}:
            raise ValueError('Invalid session change.')
        self.session(identity)
        with self.connect() as db:
            db.execute('UPDATE action_agent_sessions SET ' + ','.join(k + '=?' for k in fields) + ' WHERE id=?', (*fields.values(), identity))
        notify(identity)

    def io(self, identity, direction, key, data, *, token=None):
        if direction not in {'in', 'out', 'image'} or not isinstance(data, str) or len(data) > 65536 or not isinstance(key, str) or not 1 <= len(key) <= 100:
            raise ValueError('Invalid terminal data.')
        with self.connect() as db:
            row = db.execute('SELECT state,closed,token FROM action_agent_sessions WHERE id=?', (identity,)).fetchone()
            if not row:
                raise KeyError(identity)
            if token is not None:
                import hmac
                if not token or not hmac.compare_digest(row['token'], token):
                    raise BridgeConflict('Terminal lease does not match.')
            if direction in {'in', 'image'} and (row['closed'] or row['state'] not in {'starting','idle','waiting','running'}):
                raise BridgeConflict('Wait for the terminal to connect before typing.')
            db.execute('INSERT OR IGNORE INTO action_agent_io(session,direction,request_key,data) VALUES (?,?,?,?)', (identity, direction, key, data))
            if direction in {'in', 'image'}:
                db.execute('UPDATE action_agent_sessions SET activity=? WHERE id=?', (now(), identity))
        notify(identity)

    def stream_snapshot(self, identity, direction, after, *, token=None, include_io=True):
        """Read state and ordered I/O together without reopening the database twice."""
        with self.connect() as db:
            row = db.execute('SELECT * FROM action_agent_sessions WHERE id=?', (identity,)).fetchone()
            if row is None:
                raise KeyError(identity)
            if token is not None:
                import hmac
                if not token or not hmac.compare_digest(row['token'], token):
                    raise BridgeConflict('Terminal lease does not match.')
            rows = db.execute('SELECT seq,data,direction FROM action_agent_io INDEXED BY action_agent_io_replay WHERE session=? AND seq>? AND direction IN (?,?) ORDER BY seq LIMIT 100',
                              (identity, after, direction, 'image' if direction == 'in' else direction)) if include_io else []
            output = [{'seq': r['seq'], 'data': r['data'], **({'type': 'image'} if r['direction'] == 'image' else {})} for r in rows]
            return self.session_decode(row), output

    def read_io(self, identity, direction, after=0):
        with self.connect() as db:
            rows = db.execute('SELECT seq,data,direction FROM action_agent_io WHERE session=? AND direction IN (?,?) AND seq>? ORDER BY seq LIMIT 100', (identity, direction, 'image' if direction == 'in' else direction, after))
            return [{'seq': row['seq'], 'data': row['data'], **({'type': 'image'} if row['direction'] == 'image' else {})} for row in rows]

    def transcript(self, identity):
        self.session(identity)
        with self.connect() as db:
            return ''.join(row['data'] for row in db.execute("SELECT data FROM action_agent_io WHERE session=? AND direction='out' ORDER BY seq", (identity,)))

    def forget(self, identity):
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            row = db.execute('SELECT state FROM action_agent_sessions WHERE id=?', (identity,)).fetchone()
            if not row:
                raise KeyError(identity)
            if row['state'] not in {'closed','expired','failed'}:
                raise BridgeConflict('End the session before removing it from saved history.')
            db.execute('DELETE FROM action_agent_io WHERE session=?', (identity,))
            db.execute('DELETE FROM terminal_promotions WHERE session=?', (identity,))
            db.execute('DELETE FROM action_agent_sessions WHERE id=?', (identity,))

    def claim_session(self, identity, worker):
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            row = db.execute('SELECT * FROM action_agent_sessions WHERE id=?', (identity,)).fetchone()
            if not row or row['state'] != 'queued' or row['closed']:
                raise BridgeConflict('Session is no longer queued.')
            settings = json.loads(row['settings'])
            if settings.get('agent_host') and settings['agent_host'] != worker:
                raise BridgeConflict('Session belongs to another host.')
            token = uuid.uuid4().hex
            db.execute("UPDATE action_agent_sessions SET state='starting',worker=?,token=?,heartbeat=? WHERE id=?", (worker, token, now(), identity))
        return self.session(identity, True)

    def verify(self, identity, token):
        import hmac
        session = self.session(identity, True)
        if not token or not hmac.compare_digest(session['token'], token):
            raise BridgeConflict('Terminal lease does not match.')
        return session

    def heartbeat_session(self, identity, token, state, native_id, limit):
        if state not in {'starting','idle','waiting','running','closed','expired','failed'}:
            raise ValueError('Invalid terminal state.')
        self.verify(identity, token)
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            row = db.execute('SELECT * FROM action_agent_sessions WHERE id=?', (identity,)).fetchone()
            if row['state'] in {'failed','expired','closed'}:
                return {'granted': False, 'close': True}
            # The transaction shares the same lock and count as automatic-run claims.
            used = self.busy_count(db, exclude=identity)
            same_action = db.execute("SELECT 1 FROM agent_requests WHERE source_key=? AND state='running'", ('actionable:' + row['source_id'],)).fetchone()
            granted = state != 'waiting' or (used < limit and not same_action)
            target = 'running' if state == 'waiting' and granted else state
            db.execute('UPDATE action_agent_sessions SET state=?,native_id=?,heartbeat=?,activity=CASE WHEN state!=? THEN ? ELSE activity END WHERE id=?',
                       (target, native_id[:200], now(), target, now(), identity))
        notify(identity)
        return {'granted': granted, 'close': bool(row['closed']), 'cols': row['cols'], 'rows': row['rows']}

    @staticmethod
    def busy_count(db, exclude=''):
        automatic = db.execute("SELECT count(*) FROM agent_requests WHERE state='running'").fetchone()[0]
        interactive = db.execute("SELECT count(*) FROM action_agent_sessions WHERE state='running' AND id!=?", (exclude,)).fetchone()[0]
        return automatic + interactive

    def expire_sessions(self):
        cutoff = (datetime.now(timezone.utc) - timedelta(seconds=90)).isoformat()
        with self.connect() as db:
            db.execute("UPDATE action_agent_sessions SET state='failed', error='Worker disconnected. Restore the saved context or start a new session.' WHERE state IN ('starting','idle','waiting','running') AND heartbeat<?", (cutoff,))
            db.execute("UPDATE action_agent_sessions SET state='closed' WHERE state='queued' AND closed=1")
