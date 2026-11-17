"""Owner-scoped discovered identities and many-to-many fleet associations.

Merges are reversible overlays: source identities and observations remain intact,
so subsequent discovery cannot recreate a merged node or lose its provenance.
"""
import hashlib
import json
import os
import uuid
from contextlib import contextmanager

from fastapi import HTTPException
from modules.agents import service, projection
from workflows.hfl.agent_fleet_store import now

KINDS = {'connector', 'application', 'account', 'schedule', 'task'}


@contextmanager
def connection():
    with service.store().connect() as db:
        db.executescript('''
            CREATE TABLE IF NOT EXISTS fleet_entities (
                owner TEXT, id TEXT, payload TEXT NOT NULL, PRIMARY KEY(owner,id));
            CREATE TABLE IF NOT EXISTS fleet_entity_edges (
                owner TEXT, source TEXT, target TEXT, relation TEXT,
                PRIMARY KEY(owner,source,target,relation));
            CREATE TABLE IF NOT EXISTS fleet_entity_merges (
                owner TEXT, id TEXT, source TEXT, target TEXT, active INTEGER, created TEXT,
                PRIMARY KEY(owner,id));
        ''')
        yield db


def identity(kind, namespace, remote_id):
    return 'entity:' + hashlib.sha256(json.dumps([kind, namespace, remote_id]).encode()).hexdigest()


def entity(kind, namespace, remote_id, label, **metadata):
    if kind not in KINDS or not all(isinstance(v, str) and 0 < len(v) <= 2000 for v in (namespace, remote_id, label)):
        raise ValueError('Invalid entity identity or label.')
    from modules.agents.ecosystem import safe_url
    return dict(id=identity(kind, namespace, remote_id), kind=kind, namespace=namespace,
                remote_id=remote_id, label=label[:300], source=metadata.get('source', ''),
                summary=str(metadata.get('summary', ''))[:1000], url=safe_url(metadata.get('url', ''), allow_http=True),
                state=str(metadata.get('state', 'observed'))[:80], observed_at=now(),
                scope=metadata.get('scope', namespace), category=metadata.get('category', ''),
                mock=bool(metadata.get('mock', False)))


def observe(user, rows, edges):
    """Commit a complete, validated adapter batch; never remove prior observations."""
    with connection() as db:
        db.execute('BEGIN IMMEDIATE')
        for row in rows:
            db.execute('INSERT INTO fleet_entities VALUES (?,?,?) ON CONFLICT(owner,id) DO UPDATE SET payload=excluded.payload',
                       (user, row['id'], json.dumps(row)))
        for source, target, relation in edges:
            db.execute('INSERT OR IGNORE INTO fleet_entity_edges VALUES (?,?,?,?)', (user, source, target, relation))


def stale(user, scope, category, state):
    with connection() as db:
        rows = db.execute('SELECT id,payload FROM fleet_entities WHERE owner=?', (user,)).fetchall()
        for row in rows:
            value = json.loads(row['payload'])
            if value['scope'] == scope and value['category'] == category:
                value['state'] = state
                db.execute('UPDATE fleet_entities SET payload=? WHERE owner=? AND id=?', (json.dumps(value), user, row['id']))


def reconcile(user, scope, category, rows, edges):
    with connection() as db:
        db.execute('BEGIN IMMEDIATE')
        present = {r['id'] for r in rows}
        for saved in db.execute('SELECT id,payload FROM fleet_entities WHERE owner=?', (user,)).fetchall():
            value = json.loads(saved['payload'])
            if value['scope'] == scope and value['category'] == category and value['id'] not in present:
                value['state'] = 'no longer observed'
                db.execute('UPDATE fleet_entities SET payload=? WHERE owner=? AND id=?', (json.dumps(value), user, value['id']))
        for row in rows:
            db.execute('INSERT INTO fleet_entities VALUES (?,?,?) ON CONFLICT(owner,id) DO UPDATE SET payload=excluded.payload', (user, row['id'], json.dumps(row)))
            if row['kind'] == 'schedule':
                db.execute("DELETE FROM fleet_entity_edges WHERE owner=? AND source=? AND relation='watches'", (user, row['id']))
        for source, target, relation in edges:
            db.execute('INSERT OR IGNORE INTO fleet_entity_edges VALUES (?,?,?,?)', (user, source, target, relation))


def snapshot(user):
    with connection() as db:
        rows = {r['id']: json.loads(r['payload']) for r in db.execute('SELECT * FROM fleet_entities WHERE owner=?', (user,))}
        edges = [dict(r) for r in db.execute('SELECT source,target,relation FROM fleet_entity_edges WHERE owner=?', (user,))]
        merges = [dict(r) for r in db.execute('SELECT id,source,target,active,created FROM fleet_entity_merges WHERE owner=? ORDER BY created DESC', (user,))]
    if os.getenv('HFL_TIMELINE_LOCAL_PREVIEW') != '1':
        hidden = {i for i, v in rows.items() if v.get('mock')}
        rows = {i: v for i, v in rows.items() if i not in hidden}
        edges = [e for e in edges if e['source'] not in hidden and e['target'] not in hidden]
        merges = [m for m in merges if m['source'] not in hidden and m['target'] not in hidden]
    aliases = {m['source']: m['target'] for m in merges if m['active']}
    nodes = {i: {**v, 'provenance': [dict(source=v['source'], namespace=v['namespace'], remote_id=v['remote_id'])]} for i, v in rows.items() if i not in aliases}
    for source, target in aliases.items():
        v = rows[source]
        nodes[target]['provenance'].append(dict(source=v['source'], namespace=v['namespace'], remote_id=v['remote_id']))
    links = {(aliases.get(e['source'], e['source']), aliases.get(e['target'], e['target']), e['relation']) for e in edges}
    return {'items': list(nodes.values()), 'edges': [dict(source=s, target=t, relation=r) for s, t, r in sorted(links) if s != t], 'merges': merges}


def associate(user, agent_id, entity_id, linked):
    if type(linked) is not bool:
        raise ValueError('Choose whether to link this entity.')
    if agent_id not in {a['id'] for a in projection.listing(user)}:
        raise HTTPException(404, 'Agent unavailable.')
    if entity_id not in {r['id'] for r in snapshot(user)['items']}:
        raise HTTPException(404, 'Entity unavailable.')
    with connection() as db:
        if linked:
            db.execute('INSERT OR IGNORE INTO fleet_entity_edges VALUES (?,?,?,?)', (user, 'agent:'+agent_id, entity_id, 'linked'))
        else:
            targets = [entity_id] + [r['source'] for r in db.execute('SELECT source FROM fleet_entity_merges WHERE owner=? AND active=1 AND target=?', (user, entity_id))]
            for target in targets:
                db.execute('DELETE FROM fleet_entity_edges WHERE owner=? AND source=? AND target=? AND relation=?', (user, 'agent:'+agent_id, target, 'linked'))
    return {'ok': True}


def merge(user, source, target, confirmed=False):
    if not all(isinstance(v, str) and v.startswith('entity:') and len(v) <= 100 for v in (source, target)):
        raise ValueError('Choose two entity identities.')
    with connection() as db:
        db.execute('BEGIN IMMEDIATE')
        rows = {r['id']: json.loads(r['payload']) for r in db.execute('SELECT * FROM fleet_entities WHERE owner=? AND id IN (?,?)', (user, source, target))}
        if source == target or len(rows) != 2:
            raise HTTPException(404, 'Choose two available entities.')
        a, b = rows[source], rows[target]
        if a.get('mock') != b.get('mock') or (a.get('mock') and os.getenv('HFL_TIMELINE_LOCAL_PREVIEW') != '1'):
            raise ValueError('Keep preview entities separate from real identities.')
        if a['kind'] != b['kind'] or (a['kind'] != 'application' and a['namespace'] != b['namespace']):
            raise ValueError('Merge only matching types within the same account or installation scope.')
        if db.execute('SELECT 1 FROM fleet_entity_merges WHERE owner=? AND active=1 AND (source IN (?,?) OR target=?)', (user, source, target, source)).fetchone():
            raise HTTPException(409, 'Undo the existing merge before changing its source or target.')
        preview = {'source': a, 'target': b, 'effect': 'Keep both source identities and all relationships; display one entity. This does not change remote accounts.'}
        if confirmed is not True:
            return preview
        mid = uuid.uuid4().hex
        db.execute('INSERT INTO fleet_entity_merges VALUES (?,?,?,?,1,?)', (user, mid, source, target, now()))
        return {**preview, 'merge_id': mid}


def unmerge(user, merge_id):
    with connection() as db:
        if not db.execute('UPDATE fleet_entity_merges SET active=0 WHERE owner=? AND id=? AND active=1', (user, merge_id)).rowcount:
            raise HTTPException(404, 'Active merge unavailable.')
    return {'ok': True}


def extend_graph(user, agents, nodes, edge, add):
    data = snapshot(user)
    known = {'agent:'+a['id']: {a['id']} for a in agents}
    # Reach a fixed point even for nested child entities; cycles terminate once
    # every reachable node has the same finite set of owning agent identities.
    changed = True
    while changed:
        changed = False
        for link in data['edges']:
            if link['source'] in known:
                target = known.setdefault(link['target'], set())
                before = len(target)
                target.update(known[link['source']])
                changed |= len(target) != before
    for item in data['items']:
        for aid in known.get(item['id'], set()):
            add(aid, item['id'], item['kind'], item['label'], item['summary'], item['url'],
                relation='associated with', source=item['source'], state=item['state'],
                entity=True, observed_at=item['observed_at'], provenance=item['provenance'], mock=item['mock'])
    for link in data['edges']:
        if (link['source'] in nodes or link['source'].startswith('agent:') and link['source'] in known) and link['target'] in nodes:
            edge(link['source'], link['target'], link['relation'])
