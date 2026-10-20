"""Audited identity quarantine shared by automatic merge and mention resolution."""
import json
import time

from workflows.hfl.entity_store import get_store, digest


def isolated_mention(entry_id, mention_id):
    return 'integrity-mention-' + digest([entry_id, mention_id])[:24]


def flagged(db):
    return {r['id']: json.loads(r['data']) for r in db.execute('SELECT * FROM entity_integrity')
            if json.loads(r['data']).get('required')}


def set_review(identity, required, reason, operation_ids, actor):
    from workflows.hfl import entity_merges
    if not reason.strip():
        raise ValueError('Record the evidence for this integrity decision')
    with get_store().connection() as db:
        db.execute('BEGIN IMMEDIATE')
        if not db.execute('SELECT 1 FROM profiles WHERE id=?', (identity,)).fetchone():
            raise ValueError('An established identity is required')
        if db.execute('SELECT 1 FROM decisions WHERE alias=? AND active=1', (identity,)).fetchone():
            raise ValueError('Review the active outer identity')
        for operation in operation_ids:
            if not db.execute('SELECT 1 FROM entity_operations WHERE request_id=?', (operation,)).fetchone():
                raise ValueError('Unknown originating operation')
        data = dict(required=required, reason=reason, operation_ids=operation_ids, updated=time.time(), actor=actor)
        db.execute('INSERT OR REPLACE INTO entity_integrity VALUES (?,?)', (identity, json.dumps(data)))
        entity_merges.record_event(db, identity, 'identity-review', actor, data, deliver=False)
        # Existing assignments remain in audit but are withheld by projection while flagged.
        db.execute('INSERT OR IGNORE INTO entity_resolution_jobs(entry_id,revision) SELECT id,hash FROM enrichment')
    return data


def reverse_separation(left_id, right_id, reason, actor):
    """Reverse only consolidation's separation, retaining unmerge/dismissal vetoes."""
    from filelock import FileLock
    from workflows.hfl import entity_matching, entity_merges
    from workflows.hfl.entity_run_storage import read_run, write_run
    if left_id == right_id or not reason.strip():
        raise ValueError('Choose two identities and record why the separation is reversed')
    store = get_store()
    with FileLock(str(store.path) + '.matching.lock', timeout=30), store.connection() as db:
        db.execute('BEGIN IMMEDIATE')
        removed = 0
        for left in entity_matching.leaves(db, left_id):
            for right in entity_matching.leaves(db, right_id):
                removed += db.execute("""DELETE FROM entity_match_blocks WHERE left_id=? AND right_id=?
                    AND reason='consolidation-separate'""", tuple(sorted((left, right)))).rowcount
        if removed:
            entity_merges.record_event(db, left_id, 'separation-reversed', actor,
                                      dict(ids=[left_id, right_id], reason=reason), deliver=False)
            active = db.execute("SELECT value FROM state WHERE key='consolidation-active'").fetchone()
            run = read_run(db, json.loads(active[0])) if active else None
            if run and run['state'] == 'running':
                for pair in run['pairs'].values():
                    if set(pair['ids']) == {left_id, right_id} and pair['state'] == 'separate':
                        pair.update(state='stale', note='Owner reversed the keep-separate decision')
                for identity in (left_id, right_id):
                    run.get('discovery_snapshots', {}).pop(identity, None)
                write_run(db, run)
            checkpoint = db.execute("SELECT value FROM state WHERE key='consolidation-checkpoint'").fetchone()
            if checkpoint:
                value = json.loads(checkpoint[0])
                for identity in (left_id, right_id):
                    value.pop(identity, None)
                db.execute("UPDATE state SET value=? WHERE key='consolidation-checkpoint'", (json.dumps(value),))
            db.execute('INSERT OR IGNORE INTO entity_resolution_jobs(entry_id,revision) SELECT id,hash FROM enrichment')
    return {'removed_blocks': removed}
