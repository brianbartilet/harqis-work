"""Account-scoped PR inbox and resumable discovery in the connector database."""
import json
import time
import uuid

from modules.integrations.store import connection


def schema(db):
    db.executescript('''
        CREATE TABLE IF NOT EXISTS github_update_scans (
            account TEXT PRIMARY KEY, cursor TEXT NOT NULL DEFAULT '{}',
            lease TEXT NOT NULL DEFAULT '', lease_until REAL NOT NULL DEFAULT 0);
        CREATE TABLE IF NOT EXISTS github_update_prs (
            account TEXT NOT NULL, identity TEXT NOT NULL, payload TEXT NOT NULL,
            pending INTEGER NOT NULL DEFAULT 1, attempted REAL NOT NULL DEFAULT 0,
            refreshed REAL NOT NULL DEFAULT 0, PRIMARY KEY(account, identity));
    ''')


class Inbox:
    def __init__(self, account):
        self.account = account
        with connection() as db:
            schema(db)

    def acquire(self):
        token = uuid.uuid4().hex
        with connection() as db:
            db.execute('BEGIN IMMEDIATE')
            db.execute('INSERT OR IGNORE INTO github_update_scans(account) VALUES (?)', (self.account,))
            changed = db.execute('UPDATE github_update_scans SET lease=?,lease_until=? WHERE account=? AND lease_until<?',
                                 (token, time.time() + 1800, self.account, time.time())).rowcount
        return token if changed else ''

    def release(self, token):
        with connection() as db:
            db.execute('UPDATE github_update_scans SET lease_until=0 WHERE account=? AND lease=?', (self.account, token))

    def cursor(self):
        with connection() as db:
            row = db.execute('SELECT cursor FROM github_update_scans WHERE account=?', (self.account,)).fetchone()
        return json.loads(row[0]) if row else {}

    def save_cursor(self, value):
        with connection() as db:
            db.execute('UPDATE github_update_scans SET cursor=? WHERE account=?', (json.dumps(value), self.account))

    def get(self, identity):
        with connection() as db:
            row = db.execute('SELECT payload FROM github_update_prs WHERE account=? AND identity=?', (self.account, identity)).fetchone()
        return json.loads(row[0]) if row else None

    def observe(self, pr):
        previous = self.get(pr['identity'])
        if previous is None and (pr['draft'] or pr['state'] != 'open'):
            return False
        value = previous or {'initial': pr, 'creation': None, 'action_id': '', 'receipt': {}}
        changed = value.get('latest') != pr
        value['latest'] = pr
        with connection() as db:
            db.execute('''INSERT INTO github_update_prs(account,identity,payload,refreshed) VALUES (?,?,?,?)
                ON CONFLICT(account,identity) DO UPDATE SET payload=excluded.payload,
                pending=MAX(pending,?),refreshed=excluded.refreshed''',
                       (self.account, pr['identity'], json.dumps(value), time.time(), int(changed)))
        return previous is None

    def save(self, identity, value, *, pending=True):
        with connection() as db:
            db.execute('UPDATE github_update_prs SET payload=?,pending=?,attempted=? WHERE account=? AND identity=?',
                       (json.dumps(value), int(pending), time.time(), self.account, identity))

    def pending(self, limit):
        with connection() as db:
            return [json.loads(row[0]) for row in db.execute(
                'SELECT payload FROM github_update_prs WHERE account=? AND pending=1 ORDER BY attempted,identity LIMIT ?',
                (self.account, limit))]

    def refresh_due(self, limit):
        with connection() as db:
            return [json.loads(row[0]) for row in db.execute(
                'SELECT payload FROM github_update_prs WHERE account=? AND refreshed<? ORDER BY refreshed,identity LIMIT ?',
                (self.account, time.time() - 300, limit))]

    def mark_refresh(self, identity):
        with connection() as db:
            db.execute('UPDATE github_update_prs SET refreshed=? WHERE account=? AND identity=?', (time.time(), self.account, identity))

    def counts(self):
        with connection() as db:
            row = db.execute('SELECT COUNT(*),COALESCE(SUM(pending),0) FROM github_update_prs WHERE account=?', (self.account,)).fetchone()
        return {'tracked': row[0], 'pending': row[1]}
