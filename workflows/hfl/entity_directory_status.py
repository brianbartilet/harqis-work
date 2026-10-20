"""Read-only explanations for identities awaiting automated work."""
import json

from workflows.hfl.entity_store import get_store


def annotate(rows):
    from workflows.hfl.entity_integrity import flagged
    from workflows.hfl.entity_run_storage import read_run
    store = get_store()
    statuses = {}
    def add(identity, state, reason):
        statuses.setdefault(identity, []).append(dict(state=state, reason=reason))
    with store.connection() as db:
        for identity, review in flagged(db).items():
            add(identity, 'integrity-review', review['reason'])
        for row in db.execute('SELECT left_id,right_id,reason FROM entity_match_blocks'):
            for identity in row[:2]:
                add(identity, 'intentionally-separate', row['reason'])
        for row in db.execute('SELECT mention_id,outcome,data FROM entity_resolution_outcomes'):
            if row['outcome'] != 'resolved':
                add(row['mention_id'], row['outcome'], json.loads(row['data']).get('next_step', 'Awaiting evidence'))
        for row in db.execute('''SELECT e.mentions,j.state,j.error FROM enrichment e
                                JOIN entity_resolution_jobs j ON j.entry_id=e.id'''):
            for mention in json.loads(row['mentions']):
                add(mention['id'], 'failed' if row['state'] == 'failed' else 'awaiting-processing',
                    row['error'] or 'Queued for mention resolution')
        active = db.execute("SELECT value FROM state WHERE key='consolidation-active'").fetchone()
        run = read_run(db, json.loads(active[0])) if active else None
        if run:
            for pair in run['pairs'].values():
                if pair['state'] in {'pending', 'deferred'}:
                    for identity in pair['ids']:
                        add(identity, 'awaiting-processing' if pair['state'] == 'pending' else
                            'integrity-review' if pair.get('reason_code') == 'conflicting-identity' else 'ambiguous',
                            pair.get('note') or pair.get('next_step') or 'Awaiting consolidation review')
    for row in rows:
        unique = {(s['state'], s['reason']): s for s in statuses.get(row['id'], [])}
        row['identity_status'] = list(unique.values())
    return rows
