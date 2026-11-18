"""Provider receipts, single-installation slots, and Action trigger schedules.

The canonical bridge remains the owner of runs and append-only history. A slot
survives process death and ambiguous HTTP delivery; only reconciliation releases it.
"""
import json
from datetime import datetime, timedelta, timezone

from workflows.hfl.agent_bridge_store import AgentBridgeStore, BridgeConflict, now


class ActionExecutionStore(AgentBridgeStore):
    def __init__(self, path):
        super().__init__(path)
        with self.connect() as db:
            db.executescript('''
                CREATE TABLE IF NOT EXISTS action_provider_receipts (
                    run_id TEXT PRIMARY KEY REFERENCES agent_requests(id),
                    installation TEXT NOT NULL, state TEXT NOT NULL,
                    request TEXT NOT NULL, receipt TEXT NOT NULL DEFAULT '{}',
                    updated_at TEXT NOT NULL
                );
                CREATE UNIQUE INDEX IF NOT EXISTS action_provider_slot
                    ON action_provider_receipts(installation) WHERE state != 'finished';
                CREATE TABLE IF NOT EXISTS action_execution_schedules (
                    source_id TEXT PRIMARY KEY, minutes INTEGER NOT NULL,
                    enabled INTEGER NOT NULL, next_at TEXT NOT NULL, actor TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS action_execution_locks (
                    name TEXT PRIMARY KEY, until_at TEXT NOT NULL, token TEXT NOT NULL
                );
            ''')

    def lock(self, name, token, seconds=240):
        until = (datetime.now(timezone.utc) + timedelta(seconds=seconds)).isoformat()
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            row = db.execute('SELECT until_at FROM action_execution_locks WHERE name=?', (name,)).fetchone()
            if row and row['until_at'] > now():
                return False
            db.execute('INSERT OR REPLACE INTO action_execution_locks VALUES (?,?,?)', (name, until, token))
        return True

    def unlock(self, name, token):
        with self.connect() as db:
            db.execute('DELETE FROM action_execution_locks WHERE name=? AND token=?', (name, token))

    def reserve(self, run_id, installation, request):
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            row = db.execute('SELECT * FROM action_provider_receipts WHERE run_id=?', (run_id,)).fetchone()
            if row:
                return False
            if db.execute("SELECT 1 FROM action_provider_receipts WHERE installation=? AND state!='finished'", (installation,)).fetchone():
                return False
            db.execute('INSERT INTO action_provider_receipts VALUES (?,?,?,?,?,?)',
                       (run_id, installation, 'submitting', json.dumps(request), '{}', now()))
        return True

    def receipts(self):
        with self.connect() as db:
            rows = db.execute("SELECT * FROM action_provider_receipts WHERE state!='finished'").fetchall()
        return [{**dict(r), 'request': json.loads(r['request']), 'receipt': json.loads(r['receipt'])} for r in rows]

    def receipt(self, run_id, state, receipt=None):
        with self.connect() as db:
            if receipt is None:
                db.execute('UPDATE action_provider_receipts SET state=?,updated_at=? WHERE run_id=?', (state, now(), run_id))
            else:
                db.execute('UPDATE action_provider_receipts SET state=?,receipt=?,updated_at=? WHERE run_id=?',
                           (state, json.dumps(receipt), now(), run_id))

    def schedule(self, source_id, minutes, enabled, actor):
        if type(minutes) is not int or not 1 <= minutes <= 10080 or type(enabled) is not bool:
            raise ValueError('Choose a schedule between 1 minute and 7 days.')
        with self.connect() as db:
            db.execute('INSERT INTO action_execution_schedules VALUES (?,?,?,?,?) ON CONFLICT(source_id) DO UPDATE SET minutes=excluded.minutes,enabled=excluded.enabled,actor=excluded.actor',
                       (source_id, minutes, int(enabled), now(), actor))

    def schedules(self):
        with self.connect() as db:
            return [dict(r) for r in db.execute('SELECT * FROM action_execution_schedules')]

    def advance(self, source_id, occurrence, minutes):
        next_at = (datetime.now(timezone.utc) + timedelta(minutes=minutes)).isoformat()
        with self.connect() as db:
            db.execute('UPDATE action_execution_schedules SET next_at=? WHERE source_id=? AND next_at=?',
                       (next_at, source_id, occurrence))
