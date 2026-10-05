"""SQLite catalog shared by the frontend and its host-affine Celery worker."""
from __future__ import annotations

import json
import os
import secrets
import sqlite3
import time
import uuid
from contextlib import contextmanager
from pathlib import Path


def identity():
    return uuid.uuid4().hex


class Store:
    def __init__(self, path=None):
        self.path = Path(path or os.environ.get('FILES_STORE_PATH', 'results/files/catalog.sqlite3')).resolve()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as db:
            if db.execute('PRAGMA user_version').fetchone()[0] > 1:
                raise RuntimeError('Catalog schema is newer than this application; restore the matching release')
            db.executescript('''
                CREATE TABLE IF NOT EXISTS sources(id TEXT PRIMARY KEY, data TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS files(id TEXT PRIMARY KEY, data TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS locations(
                    id TEXT PRIMARY KEY, file_id TEXT NOT NULL, source_id TEXT NOT NULL,
                    locator TEXT NOT NULL, data TEXT NOT NULL, UNIQUE(source_id,locator));
                CREATE INDEX IF NOT EXISTS locations_file ON locations(file_id);
                CREATE TABLE IF NOT EXISTS packages(id TEXT PRIMARY KEY, data TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS revisions(
                    id TEXT PRIMARY KEY, package_id TEXT NOT NULL, number INTEGER NOT NULL,
                    token TEXT NOT NULL UNIQUE, data TEXT NOT NULL, UNIQUE(package_id,number));
                CREATE TABLE IF NOT EXISTS events(
                    id INTEGER PRIMARY KEY, subject TEXT NOT NULL, at REAL NOT NULL,
                    kind TEXT NOT NULL, data TEXT NOT NULL);
                CREATE INDEX IF NOT EXISTS events_subject ON events(subject,id);
                CREATE TABLE IF NOT EXISTS leases(key TEXT PRIMARY KEY, owner TEXT, until REAL);
                PRAGMA user_version=1;
            ''')

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.path, timeout=30)
        db.row_factory = sqlite3.Row
        db.execute('PRAGMA journal_mode=WAL')
        try:
            with db:
                yield db
        finally:
            db.close()

    def get(self, table, key):
        self._table(table)
        with self.connect() as db:
            row = db.execute(f'SELECT data FROM {table} WHERE id=?', (key,)).fetchone()
        if not row:
            raise KeyError(key)
        return json.loads(row['data'])

    @staticmethod
    def _table(table):
        if table not in {'sources', 'files', 'locations', 'packages', 'revisions'}:
            raise ValueError('Unknown catalog collection')

    def all(self, table):
        self._table(table)
        with self.connect() as db:
            return [json.loads(r[0]) for r in db.execute(f'SELECT data FROM {table} ORDER BY rowid DESC')]

    def put(self, table, item):
        self._table(table)
        with self.connect() as db:
            db.execute(f'UPDATE {table} SET data=? WHERE id=?', (json.dumps(item), item['id']))

    def patch(self, table, key, changes):
        self._table(table)
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            row = db.execute(f'SELECT data FROM {table} WHERE id=?', (key,)).fetchone()
            if not row:
                raise KeyError(key)
            item = json.loads(row[0])
            item.update(changes)
            db.execute(f'UPDATE {table} SET data=? WHERE id=?', (json.dumps(item), key))
        return item

    def add(self, table, item):
        if table not in {'sources', 'files', 'packages'}:
            raise ValueError('Use specialized insertion')
        item = {**item, 'id': item.get('id') or identity()}
        with self.connect() as db:
            db.execute(f'INSERT INTO {table} VALUES (?,?)', (item['id'], json.dumps(item)))
        return item

    def event(self, subject, kind, **data):
        with self.connect() as db:
            db.execute('INSERT INTO events(subject,at,kind,data) VALUES (?,?,?,?)',
                       (subject, time.time(), kind, json.dumps(data)))

    def history(self, subject, before=0):
        with self.connect() as db:
            rows = db.execute('SELECT * FROM events WHERE subject=? AND (?=0 OR id<?) ORDER BY id DESC LIMIT 100',
                              (subject, before, before)).fetchall()
        return [{**dict(r), 'data': json.loads(r['data'])} for r in rows]

    @contextmanager
    def lease(self, key, seconds=3900):
        # Longer than the worker hard limit; process crashes recover after expiry.
        owner = identity()
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            db.execute('DELETE FROM leases WHERE until<?', (time.time(),))
            try:
                db.execute('INSERT INTO leases VALUES (?,?,?)', (key, owner, time.time() + seconds))
            except sqlite3.IntegrityError as exc:
                raise RuntimeError('Operation already running; retry later') from exc
        try:
            yield
        finally:
            with self.connect() as db:
                db.execute('DELETE FROM leases WHERE key=? AND owner=?', (key, owner))

    def observe(self, source, locator, metadata, scan_id, file_id=None, observed=True):
        metadata = {k: v for k, v in metadata.items() if k in {
            'name', 'mime_type', 'size', 'modified', 'provenance', 'etag', 'provider_version'}}
        now = time.time()
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            row = db.execute('SELECT * FROM locations WHERE source_id=? AND locator=?', (source['id'], locator)).fetchone()
            if row:
                location = json.loads(row['data'])
                file_id = row['file_id']
            else:
                file_id = file_id or identity()
                location = {'id': identity(), 'file_id': file_id, 'source_id': source['id'],
                            'locator': locator, 'first_seen': now}
            row_file = db.execute('SELECT data FROM files WHERE id=?', (file_id,)).fetchone()
            file = json.loads(row_file[0]) if row_file else {
                'id': file_id, 'first_seen': now, 'categories': source.get('categories', []),
                'tags': source.get('tags', []), 'entities': [], 'last_opened': None, 'last_downloaded': None,
            }
            if observed or not row_file:
                file.update({k: v for k, v in metadata.items() if k in {'name', 'mime_type', 'size', 'modified', 'provenance'}})
            if observed:
                file['last_seen'] = now
            location.update(metadata)
            location.update(last_seen=now if observed else None, status='available' if observed else 'unknown', scan_id=scan_id, error=None)
            db.execute('INSERT OR REPLACE INTO files VALUES (?,?)', (file_id, json.dumps(file)))
            db.execute('INSERT OR REPLACE INTO locations VALUES (?,?,?,?,?)',
                       (location['id'], file_id, source['id'], locator, json.dumps(location)))
        return file

    def locations(self, file_id):
        with self.connect() as db:
            return [json.loads(r[0]) for r in db.execute('SELECT data FROM locations WHERE file_id=?', (file_id,))]

    def catalog(self, query='', category='', status='', offset=0, limit=50):
        clauses, args = [], []
        if query:
            clauses.append("(lower(json_extract(f.data,'$.name')) LIKE ? OR lower(json_extract(f.data,'$.tags')) LIKE ?)")
            args.extend(['%' + query.lower() + '%'] * 2)
        if category:
            clauses.append("EXISTS(SELECT 1 FROM json_each(f.data,'$.categories') WHERE CAST(value AS TEXT)=?)")
            args.append(category)
        if status:
            clauses.append("EXISTS(SELECT 1 FROM locations l WHERE l.file_id=f.id AND json_extract(l.data,'$.status')=?)")
            args.append(status)
        where = ' WHERE ' + ' AND '.join(clauses) if clauses else ''
        with self.connect() as db:
            total = db.execute('SELECT count(*) FROM files f' + where, args).fetchone()[0]
            rows = db.execute('SELECT f.data FROM files f' + where + ' ORDER BY f.rowid DESC LIMIT ? OFFSET ?',
                              (*args, min(limit, 200), max(offset, 0))).fetchall()
        items = [json.loads(r[0]) for r in rows]
        for item in items:
            item['locations'] = self.locations(item['id'])
        return {'items': items, 'total': total}

    def revision(self, package_id, file_ids, actor, request_id):
        if not file_ids or len(file_ids) > 500:
            raise ValueError('Select between 1 and 500 files')
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            existing = db.execute('SELECT data FROM revisions WHERE id=?', (request_id,)).fetchone()
            if existing:
                item = json.loads(existing[0])
                if item['package_id'] != package_id or item['file_ids'] != list(dict.fromkeys(file_ids)):
                    raise ValueError('Request ID already used for another revision')
                return item
            package_row = db.execute('SELECT data FROM packages WHERE id=?', (package_id,)).fetchone()
            if not package_row:
                raise KeyError(package_id)
            package = json.loads(package_row[0])
            snapshots = []
            for key in dict.fromkeys(file_ids):
                row = db.execute('SELECT data FROM files WHERE id=?', (key,)).fetchone()
                if not row:
                    raise ValueError('Selected file no longer exists')
                snapshots.append(json.loads(row[0]))
            number = db.execute('SELECT coalesce(max(number),0)+1 FROM revisions WHERE package_id=?', (package_id,)).fetchone()[0]
            item = {'id': request_id, 'package_id': package_id, 'number': number,
                    'token': secrets.token_urlsafe(32), 'title': package['title'], 'description': package['description'],
                    'expiry_days': package['expiry_days'], 'file_ids': list(dict.fromkeys(file_ids)),
                    'files': snapshots, 'created_at': time.time(), 'actor': actor, 'state': 'draft',
                    'copies': {}, 'folder_id': None, 'permission_id': None, 'expires_at': None}
            db.execute('INSERT INTO revisions VALUES (?,?,?,?,?)',
                       (item['id'], package_id, number, item['token'], json.dumps(item)))
        self.event(package_id, 'revision_created', revision=item['id'], actor=actor)
        return item

    def guest(self, token):
        with self.connect() as db:
            row = db.execute('SELECT data FROM revisions WHERE token=?', (token,)).fetchone()
        if not row:
            raise KeyError(token)
        item = json.loads(row[0])
        if item['state'] != 'published' or (item['expires_at'] and item['expires_at'] <= time.time()):
            raise KeyError(token)
        return item
