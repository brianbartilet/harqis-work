"""Rebuildable entity metadata, reversible identity decisions, and durable work intent."""
from __future__ import annotations
from contextlib import nullcontext

import hashlib
import json
import os
import sqlite3
from contextlib import contextmanager
from pathlib import Path


VERSION = 'corpus-entities-v1'


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def identity_resolver(db):
    """Resolve aliases from one snapshot without opening nested database readers."""
    aliases = {row['alias']: row['canonical'] for row in db.execute(
        'SELECT alias,canonical FROM decisions WHERE active=1')}
    def resolve(identity):
        seen = set()
        while identity in aliases and identity not in seen:
            seen.add(identity)
            identity = aliases[identity]
        return identity
    return resolve


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
                CREATE TABLE IF NOT EXISTS entity_activity_links(entity_id TEXT NOT NULL, entry_id TEXT NOT NULL,
                    actor TEXT NOT NULL, created TEXT NOT NULL, PRIMARY KEY(entity_id,entry_id));
                CREATE TABLE IF NOT EXISTS entity_souls(id TEXT PRIMARY KEY, version INTEGER NOT NULL, data TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS entity_resolutions(entry_id TEXT NOT NULL, mention_id TEXT NOT NULL,
                    target_id TEXT NOT NULL, data TEXT NOT NULL, PRIMARY KEY(entry_id,mention_id));
                CREATE TABLE IF NOT EXISTS entity_resolution_jobs(entry_id TEXT PRIMARY KEY, revision TEXT NOT NULL,
                    queued_at REAL NOT NULL DEFAULT 0);
                CREATE TABLE IF NOT EXISTS entity_resolution_outcomes(entry_id TEXT NOT NULL, mention_id TEXT NOT NULL,
                    outcome TEXT NOT NULL, evidence_version TEXT NOT NULL, data TEXT NOT NULL,
                    updated REAL NOT NULL, PRIMARY KEY(entry_id,mention_id));
                CREATE TABLE IF NOT EXISTS entity_integrity(id TEXT PRIMARY KEY, data TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS entity_search_features(id TEXT PRIMARY KEY, input TEXT NOT NULL, data TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS consolidation_pairs(run_id TEXT NOT NULL, id TEXT NOT NULL,
                    data TEXT NOT NULL, PRIMARY KEY(run_id,id));
                CREATE TABLE IF NOT EXISTS consolidation_evidence(run_id TEXT NOT NULL, id TEXT NOT NULL,
                    data TEXT NOT NULL, PRIMARY KEY(run_id,id));
                CREATE TABLE IF NOT EXISTS entity_merges(id TEXT PRIMARY KEY, kind TEXT NOT NULL,
                    name TEXT NOT NULL, members TEXT NOT NULL, active INTEGER NOT NULL DEFAULT 1);
                CREATE TABLE IF NOT EXISTS entity_operations(request_id TEXT PRIMARY KEY,
                    fingerprint TEXT NOT NULL, result TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS entity_match_jobs(id TEXT PRIMARY KEY, mode TEXT NOT NULL,
                    seeds TEXT NOT NULL, state TEXT NOT NULL DEFAULT 'pending', queued_at REAL DEFAULT 0,
                    error TEXT NOT NULL DEFAULT '', created TEXT DEFAULT CURRENT_TIMESTAMP);
                CREATE TABLE IF NOT EXISTS entity_match_pairs(id TEXT PRIMARY KEY, job_id TEXT NOT NULL,
                    left_id TEXT NOT NULL, right_id TEXT NOT NULL, state TEXT NOT NULL DEFAULT 'pending',
                    data TEXT NOT NULL DEFAULT '{}');
                CREATE INDEX IF NOT EXISTS entity_match_pair_identity ON entity_match_pairs(left_id,right_id,state);
                CREATE TABLE IF NOT EXISTS entity_match_blocks(left_id TEXT NOT NULL, right_id TEXT NOT NULL,
                    reason TEXT NOT NULL, PRIMARY KEY(left_id,right_id));
                CREATE TABLE IF NOT EXISTS entity_audit(id TEXT PRIMARY KEY, entity_id TEXT NOT NULL,
                    action TEXT NOT NULL, actor TEXT NOT NULL, created TEXT NOT NULL, data TEXT NOT NULL,
                    delivery TEXT NOT NULL DEFAULT 'pending', error TEXT NOT NULL DEFAULT '');
            ''')
            if 'types_revision' not in {r[1] for r in db.execute('PRAGMA table_info(enrichment)')}:
                db.execute("ALTER TABLE enrichment ADD COLUMN types_revision TEXT NOT NULL DEFAULT ''")
            if 'merge_id' not in {r[1] for r in db.execute('PRAGMA table_info(decisions)')}:
                db.execute('ALTER TABLE decisions ADD COLUMN merge_id TEXT')
            if 'queued_at' not in {r[1] for r in db.execute('PRAGMA table_info(pending)')}:
                db.execute('ALTER TABLE pending ADD COLUMN queued_at REAL DEFAULT 0')
            columns = {r[1] for r in db.execute('PRAGMA table_info(entity_resolution_jobs)')}
            for name, definition in {
                'created_at': 'REAL NOT NULL DEFAULT 0',
                'attempts': 'INTEGER NOT NULL DEFAULT 0',
                'next_attempt': 'REAL NOT NULL DEFAULT 0',
                'state': "TEXT NOT NULL DEFAULT 'pending'",
                'error': "TEXT NOT NULL DEFAULT ''",
            }.items():
                if name not in columns:
                    db.execute(f'ALTER TABLE entity_resolution_jobs ADD COLUMN {name} {definition}')
            # Legacy age is unknown: timestamp its first observation, not its last dispatch.
            db.execute("UPDATE entity_resolution_jobs SET created_at=unixepoch() WHERE created_at=0")
            db.executescript('''
                CREATE TRIGGER IF NOT EXISTS resolution_job_created AFTER INSERT ON entity_resolution_jobs
                BEGIN
                    UPDATE entity_resolution_jobs SET created_at=unixepoch() WHERE entry_id=NEW.entry_id AND created_at=0;
                    INSERT INTO state(key,value) VALUES ('resolution-received','1')
                    ON CONFLICT(key) DO UPDATE SET value=CAST(CAST(value AS INTEGER)+1 AS TEXT);
                END;
            ''')

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

    def save(self, identity, content_hash, mentions, version=VERSION, match=False, types_revision=''):
        with self.connection() as db:
            previous = db.execute('SELECT hash,version,mentions,types_revision FROM enrichment WHERE id=?', (identity,)).fetchone()
            encoded_mentions = json.dumps(mentions)
            changed = previous is None or tuple(previous) != (content_hash, version, encoded_mentions, types_revision)
            db.execute('INSERT OR REPLACE INTO enrichment(id,hash,version,mentions,types_revision) VALUES (?,?,?,?,?)',
                       (identity, content_hash, version, encoded_mentions, types_revision))
            if changed:
                db.execute('''DELETE FROM entity_resolution_outcomes WHERE entry_id=? AND mention_id NOT IN
                    (SELECT json_extract(value,'$.id') FROM json_each(?))''', (identity, encoded_mentions))
            if match and changed:
                db.execute('INSERT OR REPLACE INTO entity_resolution_jobs(entry_id,revision) VALUES (?,?)',
                           (identity, content_hash))
                db.execute('''INSERT OR IGNORE INTO entity_resolution_jobs(entry_id,revision)
                    SELECT DISTINCT e.id,e.hash FROM entity_resolutions r
                    JOIN enrichment e ON e.id=r.entry_id, json_each(r.data, '$.evidence_hashes') dependency
                    WHERE dependency.key=?''', (identity,))
                # Reopen unresolved comparisons whose candidate acquired changed source evidence.
                targets = {m['id'] for m in mentions}
                if previous:
                    targets |= {m['id'] for m in json.loads(previous['mentions'])}
                resolve = identity_resolver(db)
                targets |= {resolve(i) for i in targets}
                for row in db.execute("SELECT entry_id,data FROM entity_resolution_outcomes WHERE outcome!='resolved'"):
                    if targets.intersection(json.loads(row['data']).get('candidate_ids', [])):
                        db.execute('''INSERT OR IGNORE INTO entity_resolution_jobs(entry_id,revision)
                            SELECT id,hash FROM enrichment WHERE id=?''', (row['entry_id'],))
            if match and mentions:
                from workflows.hfl.entity_matching import enabled
                owner = db.execute("SELECT value FROM state WHERE key='entity-consolidation-owner'").fetchone()
                if enabled() and not (owner and json.loads(owner[0]) == 'hermes'):
                    job_id = 'enrichment-' + digest([identity, content_hash, version, types_revision])
                    db.execute('INSERT OR IGNORE INTO entity_match_jobs(id,mode,seeds) VALUES (?,?,?)',
                               (job_id, 'enrichment', json.dumps(sorted({m['id'] for m in mentions}))))

    def prune(self, current_ids):
        with self.connection() as db:
            old = {r[0] for r in db.execute('SELECT id FROM enrichment')}
            removed = old - set(current_ids)
            db.executemany('DELETE FROM enrichment WHERE id=?', [(i,) for i in removed])
            db.executemany('DELETE FROM entity_resolution_jobs WHERE entry_id=?', [(i,) for i in removed])
            db.executemany('DELETE FROM entity_resolution_outcomes WHERE entry_id=?', [(i,) for i in removed])
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

    def undo(self, decision_id, actor='owner'):
        with self.connection() as db:
            db.execute('BEGIN IMMEDIATE')
            row = db.execute('SELECT * FROM decisions WHERE id=?', (decision_id,)).fetchone()
            if row and row['merge_id']:
                raise ValueError('Use Unmerge on the merged entity to reverse the complete group')
            if row and self.resolve(row['canonical']) != row['canonical']:
                raise ValueError('Unmerge the outer grouping first')
            if row and row['active']:
                from workflows.hfl.entity_merges import record_event
                from workflows.hfl.entity_matching import block_members
                block_members(db, [row['alias'],row['canonical']], 'unmerged')
                profiles = {r['id']: json.loads(r['data']) for r in db.execute('SELECT id,data FROM profiles')}
                record_event(db, row['canonical'], 'unmerged', actor, {
                    'name': profiles.get(row['canonical'], {}).get('name', row['canonical']),
                    'members': [{'id': identity, 'label': profiles.get(identity, {}).get('name', identity)}
                                for identity in (row['alias'], row['canonical'])],
                    'evidence': row['reason'], 'legacy_decision_id': decision_id,
                })
            db.execute('UPDATE decisions SET active=0 WHERE id=?', (decision_id,))

    def profiles(self):
        with self.connection() as db:
            return {r['id']: {**json.loads(r['data']), 'id': r['id'], 'kind': r['kind'],
                              'updated': r['updated']}
                    for r in db.execute('SELECT * FROM profiles')}

    def save_profile(self, identity, kind, data, actor='owner', connection=None):
        # Curated data is never pruned or overwritten by enrichment.
        with (nullcontext(connection) if connection is not None else self.connection()) as db:
            if connection is None:
                db.execute('BEGIN IMMEDIATE')
            if db.execute('SELECT 1 FROM decisions WHERE alias=? AND active=1', (identity,)).fetchone():
                raise ValueError('Entity was merged; refresh before editing its profile')
            group = db.execute('SELECT * FROM entity_merges WHERE id=?', (identity,)).fetchone()
            if group and not group['active']:
                raise ValueError('Entity was unmerged; refresh before editing its profile')
            previous = db.execute('SELECT data,kind FROM profiles WHERE id=?', (identity,)).fetchone()
            old_sources = json.loads(previous[0]).get('alias_sources', {}) if previous else {}
            data = dict(data)
            data['alias_sources'] = {v: old_sources.get(v, 'user') for k in ('aliases', 'partial_aliases') for v in data.get(k, [])}
            if group:
                from workflows.hfl.entity_merges import record_event
                old = db.execute('SELECT data FROM profiles WHERE id=?', (identity,)).fetchone()
                record_event(db, identity, 'profile-edited', actor, {
                    'name': data['name'], 'members': json.loads(group['members']),
                    'before': json.loads(old[0]) if old else None, 'profile': data,
                }, deliver=False)
            if group:
                db.execute('UPDATE entity_merges SET kind=?,name=? WHERE id=?', (kind, data['name'], identity))
            db.execute("INSERT INTO profiles(id,kind,data) VALUES (?,?,?) ON CONFLICT(id) "
                       "DO UPDATE SET data=excluded.data, kind=excluded.kind, updated=CURRENT_TIMESTAMP",
                       (identity, kind, json.dumps(data)))
            db.execute('''INSERT OR IGNORE INTO entity_resolution_jobs(entry_id,revision)
                SELECT e.id,e.hash FROM enrichment e JOIN entity_resolutions r ON e.id=r.entry_id
                WHERE r.target_id=?''', (identity,))
            from workflows.hfl.entity_resolution import invalidate_targets
            invalidate_targets(db, [identity])
            # A new or edited target can resolve previously unmatched mentions.
            if not previous or previous['kind'] != kind or json.loads(previous[0]) != data:
                from workflows.hfl.entity_candidates import similarity
                target = dict(id=identity, kind=kind, label=data['name'], profile=data, entries=[])
                for row in db.execute('''SELECT o.entry_id,o.mention_id,o.data,e.mentions
                    FROM entity_resolution_outcomes o JOIN enrichment e ON e.id=o.entry_id
                    WHERE o.outcome IN ('ambiguous','no-candidate','integrity-review')'''):
                    candidate_ids = json.loads(row['data']).get('candidate_ids', [])
                    mention = next((m for m in json.loads(row['mentions']) if m['id'] == row['mention_id']), None)
                    signals = similarity(mention, target) if mention and mention['kind'] == kind else {}
                    if identity in candidate_ids or signals.get('exact') or signals.get('partial') or signals.get('contact') or signals.get('fuzzy', 0) >= .8:
                        db.execute('''INSERT OR IGNORE INTO entity_resolution_jobs(entry_id,revision)
                            SELECT id,hash FROM enrichment WHERE id=?''', (row['entry_id'],))

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
