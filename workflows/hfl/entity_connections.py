"""Atomic connection edits using the existing soul relationship records."""
from contextlib import nullcontext
import json
from datetime import datetime, timezone

from workflows.hfl.entity_store import get_store
from workflows.hfl.entity_soul import all_souls, empty


def activity_links(connection=None):
    with (nullcontext(connection) if connection is not None else get_store().connection()) as db:
        return [dict(r) for r in db.execute('SELECT * FROM entity_activity_links')]


def edit(identity, changes, actor, available, entry_ids, versions, connection=None):
    store = get_store()
    with (nullcontext(connection) if connection is not None else store.connection()) as db:
        if connection is None:
            db.execute('BEGIN IMMEDIATE')
        if identity not in available or store.resolve(identity) != identity:
            raise ValueError('Entity changed or unavailable; refresh before saving')
        souls = all_souls(db)
        for source in {c.get('source_id') or identity for c in changes}:
            if versions.get(source) != souls.get(source, {}).get('version', 0):
                raise ValueError('Connections changed; close and reopen before saving')
        now = datetime.now(timezone.utc).isoformat()
        for change in changes:
            source = change.get('source_id') or identity
            target = change['target_id']
            activity = change['activity']
            if source != identity and (target != identity or activity):
                raise ValueError('Connection does not belong to this entity')
            if source not in available or store.resolve(source) != source:
                raise ValueError('Source entity changed; refresh before saving')
            if activity:
                if target not in entry_ids:
                    raise ValueError('Activity unavailable')
                owners = [r[0] for r in db.execute('SELECT entity_id FROM entity_activity_links WHERE entry_id=?', (target,))
                          if store.resolve(r[0]) == source]
                if change['remove']:
                    db.executemany('DELETE FROM entity_activity_links WHERE entity_id=? AND entry_id=?', [(owner, target) for owner in owners])
                elif not owners:
                    db.execute('INSERT OR IGNORE INTO entity_activity_links VALUES (?,?,?,?)', (source, target, actor, now))
                continue
            if target not in available or target == source or store.resolve(target) != target:
                raise ValueError('Choose another current entity')
            soul = souls.setdefault(source, empty())
            rows = soul['relationships']
            existing = next((r for r in rows if r['id'] == change['id']), None)
            if change['remove']:
                if existing and store.resolve(existing['target_id']) != target:
                    raise ValueError('Connection changed; refresh before removing')
                soul['relationships'] = [r for r in rows if r['id'] != change['id']]
            else:
                record = {k: change[k] for k in ('id', 'target_id', 'relation', 'since', 'until', 'evidence')}
                duplicate = next((r for r in rows if store.resolve(r['target_id']) == target and all(r.get(k, '') == record[k] for k in ('relation', 'since', 'until'))), None)
                if record['relation'] in {'related_to', 'colleague_of'}:
                    reverse = next((r for r in souls.get(target, {}).get('relationships', [])
                                    if store.resolve(r['target_id']) == source and all(r.get(k, '') == record[k] for k in ('relation', 'since', 'until'))), None)
                    duplicate = duplicate or reverse
                if duplicate and not existing:
                    continue
                if duplicate and duplicate['id'] != record['id']:
                    raise ValueError('This connection already exists; edit the existing connection')
                record['provenance'] = dict(actor=actor, at=now, basis='user-confirmed')
                soul['relationships'] = [r for r in rows if r['id'] != record['id']] + [record]
            if len(soul['relationships']) > 100:
                raise ValueError('Use at most 100 connections per entity')
            soul['updated_by'] = actor
            soul['updated_at'] = now
            soul['version'] += 1
            db.execute('INSERT OR REPLACE INTO entity_souls VALUES (?,?,?)', (source, soul['version'], json.dumps(soul)))
        from workflows.hfl.entity_merges import record_event
        record_event(db, identity, 'connections-edited', actor, {'name': available[identity]['label'], 'changes': changes}, deliver=False)
    return {'saved': True}
