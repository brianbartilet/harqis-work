"""Explicit, backed-up removal of retired Topic projections; never edits corpus text."""
import json
import sqlite3
from uuid import UUID

from filelock import FileLock

from workflows.hfl.entity_store import get_store, digest, identity_resolver


def _selection(db):
    profiles = {r['id']: r['kind'] for r in db.execute('SELECT id,kind FROM profiles')}
    resolve = identity_resolver(db)
    records = [dict(r) for r in db.execute('SELECT id,mentions FROM enrichment')]
    retired = {i for i, kind in profiles.items() if kind == 'topics'
               and profiles.get(resolve(i), kind) == 'topics'}
    retired.update(r['id'] for r in db.execute("SELECT id FROM entity_merges WHERE kind='topics'")
                   if profiles.get(resolve(r['id']), 'topics') == 'topics')
    updates, removed = [], 0
    for row in records:
        before = json.loads(row['mentions'])
        after = []
        for mention in before:
            kind = profiles.get(resolve(mention['id']), profiles.get(mention['id'], mention['kind']))
            if kind == 'topics':
                retired.add(mention['id'])
                removed += 1
            else:
                # Preserve explicitly retyped identities even if extraction still says Topics.
                after.append({**mention, 'kind': kind} if mention['kind'] == 'topics' else mention)
        if before != after:
            updates.append((json.dumps(after), row['id']))
    return retired, updates, removed


def _hash(db, ids, updates):
    from workflows.hfl.entity_merges import revision
    return digest([sorted(ids), updates, revision(db)])


def preview():
    with get_store().connection() as db:
        db.execute('BEGIN')
        ids, updates, mentions = _selection(db)
        return dict(kind='topics', entities=len(ids), mentions=mentions, activities=len(updates),
                    selection_hash=_hash(db, ids, updates), preserves_activity_text=True)


def remove_topics(request_id, selection_hash, actor):
    """Idempotent owner operation with an on-host SQLite backup and stale-preview check."""
    UUID(request_id)
    store = get_store()
    fingerprint = digest(['remove-topics', selection_hash])
    from workflows.hfl.entity_merges import existing_operation, record_event
    from workflows.hfl.entity_run_storage import read_run, write_run
    with FileLock(str(store.path) + '.matching.lock', timeout=30):
        with store.connection() as db:
            prior = existing_operation(db, request_id, fingerprint)
            if prior:
                return prior
        backup = store.path.with_name(store.path.name + '.before-topics-' + request_id + '.sqlite3')
        if not backup.exists():
            with store.connection() as source, sqlite3.connect(backup) as target:
                source.backup(target)
        with store.connection() as db:
            db.execute('BEGIN IMMEDIATE')
            prior = existing_operation(db, request_id, fingerprint)
            if prior:
                return prior
            ids, updates, mentions = _selection(db)
            if _hash(db, ids, updates) != selection_hash:
                raise ValueError('Topic entities changed; fetch a fresh removal preview')
            db.execute('CREATE TEMP TABLE retired_ids(id TEXT PRIMARY KEY)')
            db.executemany('INSERT INTO retired_ids VALUES (?)', [(i,) for i in ids])
            db.executemany('UPDATE enrichment SET mentions=? WHERE id=?', updates)
            for table, column in [('profiles', 'id'), ('entity_souls', 'id'),
                                  ('entity_activity_links', 'entity_id'), ('entity_integrity', 'id'),
                                  ('entity_search_features', 'id')]:
                db.execute(f'DELETE FROM {table} WHERE {column} IN (SELECT id FROM retired_ids)')
            db.execute('DELETE FROM entity_resolution_outcomes WHERE mention_id IN (SELECT id FROM retired_ids) '
                       'OR (entry_id,mention_id) IN (SELECT entry_id,mention_id FROM entity_resolutions '
                       'WHERE target_id IN (SELECT id FROM retired_ids))')
            db.execute('DELETE FROM entity_resolutions WHERE mention_id IN (SELECT id FROM retired_ids) '
                       'OR target_id IN (SELECT id FROM retired_ids)')
            db.execute("DELETE FROM entity_resolution_jobs WHERE entry_id IN (SELECT id FROM enrichment WHERE mentions='[]')")
            db.execute('UPDATE decisions SET active=0 WHERE alias IN (SELECT id FROM retired_ids) '
                       'OR canonical IN (SELECT id FROM retired_ids)')
            db.execute('UPDATE entity_merges SET active=0 WHERE id IN (SELECT id FROM retired_ids)')
            db.execute("UPDATE entity_match_pairs SET state='stale' WHERE left_id IN (SELECT id FROM retired_ids) "
                       'OR right_id IN (SELECT id FROM retired_ids)')
            for row in list(db.execute('SELECT id,data FROM entity_souls')):
                soul = json.loads(row['data'])
                relationships = soul.get('relationships', [])
                kept = [r for r in relationships if r.get('target_id') not in ids]
                if kept != relationships:
                    soul['relationships'] = kept
                    db.execute('UPDATE entity_souls SET data=?,version=version+1 WHERE id=?',
                               (json.dumps(soul), row['id']))
            for row in list(db.execute("SELECT key FROM state WHERE key LIKE 'consolidation:%'")):
                run = read_run(db, row['key'].split(':', 1)[1])
                if run.get('state') != 'running':
                    continue  # Completed reports and audit evidence are immutable history.
                changed = False
                for pair in run['pairs'].values():
                    if pair['state'] in {'pending', 'deferred'} and (pair.get('kind') == 'topics' or ids.intersection(pair['ids'])):
                        pair.update(state='stale', note='Topics retired by owner')
                        changed = True
                if changed:
                    write_run(db, run)
            for key, default in [('custom-entity-types', []), ('entity-type-overrides', {})]:
                row = db.execute('SELECT value FROM state WHERE key=?', (key,)).fetchone()
                value = json.loads(row[0]) if row else default
                value = [t for t in value if t['id'] != 'topics'] if isinstance(value, list) else {k:v for k,v in value.items() if k != 'topics'}
                db.execute('INSERT OR REPLACE INTO state VALUES (?,?)', (key, json.dumps(value)))
            result = dict(action='topics-removed', state='complete', entities=len(ids), mentions=mentions,
                          activities=len(updates), backup=str(backup), request_id=request_id)
            result['event_id'] = record_event(db, 'type:topics', 'type-retired', actor, result, deliver=False)
            db.execute('INSERT INTO entity_operations VALUES (?,?,?)', (request_id, fingerprint, json.dumps(result)))
            return result
