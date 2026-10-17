"""Transactional row-based run persistence with lazy migration of legacy JSON runs."""
import json

from workflows.hfl.entity_store import digest


def write_run(db, run):
    evidence, pairs = {}, {}
    for identity, pair in run['pairs'].items():
        row = dict(pair)
        for side in ('left', 'right'):
            value = row.pop(side)
            key = digest(value)
            evidence[key] = json.dumps(value, ensure_ascii=False, sort_keys=True)
            row[side + '_evidence'] = key
        pairs[identity] = json.dumps(row, ensure_ascii=False, sort_keys=True)
    for table, values in [('consolidation_evidence', evidence), ('consolidation_pairs', pairs)]:
        # A conditional UPSERT leaves unchanged pages untouched. Historical evidence
        # remains referenced by stale/decided pairs; do not discard those snapshots.
        db.executemany(f'INSERT INTO {table}(run_id,id,data) VALUES (?,?,?) '
                       'ON CONFLICT(run_id,id) DO UPDATE SET data=excluded.data '
                       f'WHERE {table}.data != excluded.data',
                       [(run['id'], key, data) for key, data in values.items()])
    metadata = {k: v for k, v in run.items() if k != 'pairs'}
    metadata['storage_version'] = 2
    db.execute('INSERT OR REPLACE INTO state VALUES (?,?)',
               ('consolidation:' + run['id'], json.dumps(metadata)))


def read_run(db, run_id):
    row = db.execute('SELECT value FROM state WHERE key=?', ('consolidation:' + run_id,)).fetchone()
    if not row:
        return None
    run = json.loads(row[0])
    if run.get('storage_version') != 2:
        return run
    evidence = {r['id']: json.loads(r['data']) for r in db.execute(
        'SELECT id,data FROM consolidation_evidence WHERE run_id=?', (run_id,))}
    run['pairs'] = {}
    for row in db.execute('SELECT id,data FROM consolidation_pairs WHERE run_id=? ORDER BY id', (run_id,)):
        pair = json.loads(row['data'])
        for side in ('left', 'right'):
            # Packets may hydrate their evidence in place; preserve per-pair isolation.
            from copy import deepcopy
            pair[side] = deepcopy(evidence[pair.pop(side + '_evidence')])
        run['pairs'][row['id']] = pair
    return run
