"""Transactional entity groups and a durable, idempotent corpus audit outbox."""
from datetime import datetime, timezone
import json
import uuid

from workflows.hfl.entity_store import digest, get_store


def revision(db):
    return digest({table: [tuple(r) for r in db.execute(query)] for table, query in {
        'enrichment': 'SELECT id,hash,version FROM enrichment ORDER BY id',
        'profiles': 'SELECT id,kind,data FROM profiles ORDER BY id',
        'decisions': 'SELECT * FROM decisions ORDER BY id',
        'merges': 'SELECT * FROM entity_merges ORDER BY id',
    }.items()})


def record_event(db, identity, action, actor, data, *, deliver=True):
    event_id = str(uuid.uuid4())
    db.execute('INSERT INTO entity_audit(id,entity_id,action,actor,created,data,delivery) VALUES (?,?,?,?,?,?,?)',
               (event_id, identity, action, actor, datetime.now(timezone.utc).isoformat(),
                json.dumps(data), 'pending' if deliver else 'not-required'))
    return event_id


def operation(request_id, fingerprint):
    with get_store().connection() as db:
        return existing_operation(db, request_id, fingerprint)


def existing_operation(db, request_id, fingerprint):
    row = db.execute('SELECT * FROM entity_operations WHERE request_id=?', (request_id,)).fetchone()
    if row:
        if row['fingerprint'] != fingerprint:
            raise ValueError('Request ID was already used for a different operation')
        return json.loads(row['result'])


def commit_merge(preview, request_id, fingerprint, actor):
    with get_store().connection() as db:
        db.execute('BEGIN IMMEDIATE')
        previous = existing_operation(db, request_id, fingerprint)
        if previous:
            return previous
        if revision(db) != preview['revision']:
            raise ValueError('Entities changed; review a fresh merge preview')
        identity = 'merged-' + uuid.uuid4().hex
        members = preview['members']
        db.execute('INSERT INTO entity_merges(id,kind,name,members) VALUES (?,?,?,?)',
                   (identity, preview['kind'], preview['name'], json.dumps(members)))
        db.execute('INSERT INTO profiles(id,kind,data) VALUES (?,?,?)',
                   (identity, preview['kind'], json.dumps(preview['profile'])))
        db.executemany('INSERT INTO decisions(alias,canonical,reason,merge_id) VALUES (?,?,?,?)',
                       [(m['id'], identity, preview['evidence'], identity) for m in members])
        event_id = record_event(db, identity, 'merged', actor, {
            'name': preview['name'], 'kind': preview['kind'], 'members': members,
            'profile': preview['profile'], 'evidence': preview['evidence'],
            'unique_entries': preview['unique_entries'],
        })
        result = dict(entity_id=identity, event_id=event_id, state='complete', action='merged')
        db.execute('INSERT INTO entity_operations VALUES (?,?,?)', (request_id, fingerprint, json.dumps(result)))
        return result


def unmerge(identity, request_id, fingerprint, actor, evidence=''):
    with get_store().connection() as db:
        db.execute('BEGIN IMMEDIATE')
        previous = existing_operation(db, request_id, fingerprint)
        if previous:
            return previous
        if db.execute('SELECT 1 FROM decisions WHERE alias=? AND active=1', (identity,)).fetchone():
            raise ValueError('Unmerge the outer grouping first')
        group = db.execute('SELECT * FROM entity_merges WHERE id=? AND active=1', (identity,)).fetchone()
        if not group:
            raise ValueError('No active merge exists for this entity')
        row = db.execute('SELECT data FROM profiles WHERE id=?', (identity,)).fetchone()
        profile = json.loads(row[0]) if row else {}
        members = json.loads(group['members'])
        event_id = record_event(db, identity, 'unmerged', actor, {
            'name': profile.get('name', group['name']), 'kind': group['kind'],
            'members': members, 'profile': profile, 'evidence': evidence,
        })
        db.execute('UPDATE decisions SET active=0 WHERE merge_id=?', (identity,))
        db.execute('UPDATE entity_merges SET active=0 WHERE id=?', (identity,))
        db.execute('DELETE FROM profiles WHERE id=?', (identity,))
        result = dict(entity_id=identity, restored_ids=[m['id'] for m in members],
                      event_id=event_id, state='complete', action='unmerged')
        db.execute('INSERT INTO entity_operations VALUES (?,?,?)', (request_id, fingerprint, json.dumps(result)))
        return result


def history(identity):
    with get_store().connection() as db:
        result = []
        for row in db.execute('SELECT * FROM entity_audit ORDER BY created DESC, id'):
            data = json.loads(row['data'])
            if row['entity_id'] == identity or identity in {m['id'] for m in data.get('members', [])}:
                result.append({**dict(row), 'data': data})
        return result


def flush_audits(limit=20):
    """Submission is deterministic even after a crash between delivery and acknowledgement."""
    from workflows.hfl.dto.entry import HflEntry
    from workflows.hfl.persistence import submit_hfl_entry
    store = get_store()
    with store.connection() as db:
        rows = list(db.execute("SELECT * FROM entity_audit WHERE delivery='pending' ORDER BY created LIMIT ?", (limit,)))
    for row in rows:
        data = json.loads(row['data'])
        members = '\n'.join(f"- {m['label']} ({m['id']})" for m in data.get('members', []))
        entry = HflEntry(when=datetime.fromisoformat(row['created']),
            moment=f"Entities {row['action']}: {data['name']}",
            what_happened=f"Actor: {row['actor']}\nResult: {data['name']} ({row['entity_id']})\n"
                          f"Event: {row['id']}\nEntities:\n{members}\nDecision evidence: {data.get('evidence') or 'Not supplied'}",
            why_it_stayed='Reversible entity identity decision; original evidence and profiles retained.',
            possible_use='audit-log', tags=('entities-audit', row['action']),
            entry_id='hfl-entities-audit-' + row['id'])
        try:
            result = submit_hfl_entry(entry, source='entities-audit', dedup_key='entities-audit:' + row['id'])
            # The HFL outbox now owns any remaining delivery work.
            with store.connection() as db:
                db.execute("UPDATE entity_audit SET delivery=?,error='' WHERE id=?",
                           (result.get('delivery', 'persisted'), row['id']))
        except Exception as exc:
            with store.connection() as db:
                db.execute('UPDATE entity_audit SET error=? WHERE id=?', (type(exc).__name__, row['id']))
