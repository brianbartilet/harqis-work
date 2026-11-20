"""Owner-scoped type definitions and explicit agent-type normalization rules.

Normalization changes presentation, never source identities or permissions.
"""
import json
import re
import uuid
from contextlib import contextmanager

from modules.agents import service
from workflows.hfl.agent_fleet_store import now


DESCRIPTIONS = {
    'connector': 'Connection to an agent provider or installation.',
    'account': 'An authenticated account connected to an application.',
    'application': 'A service used by agents.', 'schedule': 'When work should run.',
    'trigger': 'An event that starts work.', 'workflow': 'A reusable sequence of work.',
    'task': 'An individual execution or unit of work.', 'skill': 'Reusable instructions available to agents.',
    'file': 'A saved or generated file.', 'entry': 'Recorded content or a conversation output.',
    'configuration': 'Settings for an agent or its environment.',
}
# Source terminology is documentation, not a claim that its API is supported.
EQUIVALENTS = [
    ('hermes', 'installation', 'connector', 'owner', 'verified'),
    ('openclaw', 'installation', 'connector', 'installation', 'documented'),
    ('openclaw', 'Fleet sessions', 'task', 'agent', 'documented'),
    ('grokbot', 'skills', 'skill', 'account', 'documented'),
    ('grokbot', 'library files', 'file', 'account', 'documented'),
    ('grokbot', 'library pages', 'entry', 'account', 'documented'),
    ('grokbot', 'routines', 'workflow', 'agent', 'documented'),
    ('grokbot', 'routine schedules', 'schedule', 'agent', 'documented'),
    ('grokbot', 'routine events', 'trigger', 'agent', 'documented'),
    ('grokbot', 'connected services', 'application', 'account', 'documented'),
    ('grokbot', 'connected accounts', 'account', 'account', 'documented'),
    ('grokbot', 'media', 'file', 'agent', 'documented'),
    ('grokbot', 'settings', 'configuration', 'agent', 'documented'),
    ('grokbot', 'memory', 'entry', 'agent', 'documented'),
    ('grokbot', 'channels', 'configuration', 'agent', 'documented'),
    ('grokbot', 'voice', 'configuration', 'agent', 'documented'),
    ('grokbot', 'registered computers', 'configuration', 'account', 'documented'),
    ('grokbot', 'app settings', 'configuration', 'account', 'documented'),
    ('grokbot', 'conversation replies', 'entry', 'agent', 'verified'),
    ('grokbot', 'connection', 'connector', 'account', 'verified'),
    ('nod', 'schedules', 'schedule', 'installation', 'verified'),
    ('nod', 'applications', 'application', 'installation', 'verified'),
    ('nod', 'connections', 'account', 'installation', 'verified'),
    ('nod', 'installation', 'connector', 'installation', 'verified'),
    ('claude', 'skills', 'skill', 'installation', 'verified'),
    ('claude', 'connector', 'connector', 'installation', 'verified'),
    ('hermes', 'skills', 'skill', 'agent', 'verified'),
    ('hermes', 'workflows', 'workflow', 'agent', 'verified'),
    ('hermes', 'triggers', 'trigger', 'agent', 'verified'),
]


@contextmanager
def connection():
    with service.store().connect() as db:
        db.executescript('''
            CREATE TABLE IF NOT EXISTS fleet_entity_types(owner TEXT,id TEXT,payload TEXT NOT NULL,PRIMARY KEY(owner,id));
            CREATE TABLE IF NOT EXISTS fleet_entity_catalog_audit(owner TEXT,id TEXT,payload TEXT NOT NULL,PRIMARY KEY(owner,id));
        ''')
        yield db


def defaults():
    from modules.agents.ecosystem import KINDS
    return {key: dict(id=key, name=key.replace('_', ' ').title(), color=color,
                     description=DESCRIPTIONS.get(key, key.replace('_', ' ').title() + ' objects in Fleet.'),
                     keywords=[key], hidden=False, builtin=True, version=0,
                     equivalents=[dict(agent_type=p, source_object=o, scope=s, status=v)
                                  for p, o, k, s, v in EQUIVALENTS if k == key])
            for key, color in {**KINDS, 'status': '#94a3b8'}.items()}


def definitions(user):
    result = defaults()
    with connection() as db:
        for row in db.execute('SELECT id,payload FROM fleet_entity_types WHERE owner=?', (user,)):
            result[row['id']] = json.loads(row['payload'])
    return result


def normalize(types, agent_type, source_object, fallback):
    for item in types.values():
        if any(m['agent_type'] == agent_type and m['source_object'].casefold() == source_object.casefold()
               for m in item['equivalents']):
            return item['id']
    return fallback


def listing(user):
    types = definitions(user)
    from modules.agents.ecosystem import graph
    graph_data = graph(user)
    counts = {key: 0 for key in types}
    for node in graph_data['nodes']:
        counts[node['kind']] = counts.get(node['kind'], 0) + 1
    counts['status'] = len({(n['kind'], n.get('state') or n.get('status') or n.get('record', {}).get('status') or 'unknown')
                            for n in graph_data['nodes'] if n['kind'] in {'action', 'idea'}})
    return {'items': [{**v, 'count': counts.get(k, 0)} for k, v in types.items()],
            'agent_types': [{'id': k, 'name': v[0]} for k, v in service.SERVICES.items()],
            'colors': service.catalogue()['colors']}


def save(user, raw):
    types = definitions(user)
    key = raw.get('id', '')
    if not isinstance(key, str) or not re.fullmatch(r'[a-z][a-z0-9_]{0,39}', key) or key in {'agent', 'owner'}:
        raise ValueError('Use a short lowercase entity type key.')
    old = types.get(key)
    if old and 'builtin' not in raw:
        raise ValueError('This type key already exists. Edit the existing type instead.')
    if raw.get('version', 0) != (old or {}).get('version', 0):
        raise ValueError('This type changed. Reload before saving.')
    item = {'id': key, 'builtin': key in defaults(), 'version': (old or {}).get('version', 0) + 1}
    for field, limit in [('name', 80), ('description', 1000), ('color', 7)]:
        value = raw.get(field, '')
        if not isinstance(value, str) or not value.strip() or len(value) > limit:
            raise ValueError('Enter a valid ' + field + '.')
        item[field] = value.strip()
    if not re.fullmatch(r'#[0-9a-fA-F]{6}', item['color']):
        raise ValueError('Choose a valid color.')
    words = raw.get('keywords', [])
    if not isinstance(words, list) or len(words) > 40 or any(not isinstance(w, str) or not w.strip() or len(w) > 80 for w in words):
        raise ValueError('Use up to 40 short mapping keywords.')
    item['keywords'] = list(dict.fromkeys(w.strip() for w in words))
    if type(raw.get('hidden', False)) is not bool:
        raise ValueError('Invalid visibility.')
    item['hidden'] = raw.get('hidden', False)
    mappings = raw.get('equivalents', [])
    if not isinstance(mappings, list) or len(mappings) > 100:
        raise ValueError('Too many equivalents.')
    item['equivalents'] = []
    used = {(m['agent_type'], m['source_object'].casefold()) for k, v in types.items() if k != key for m in v['equivalents']}
    for m in mappings:
        if not isinstance(m, dict) or m.get('agent_type') not in service.SERVICES:
            raise ValueError('Choose a supported agent type.')
        obj = m.get('source_object', '')
        if not isinstance(obj, str) or not obj.strip() or len(obj) > 100:
            raise ValueError('Enter the source object name.')
        pair = (m['agent_type'], obj.strip().casefold())
        if pair in used:
            raise ValueError('That source object already maps to a type. Remove its previous mapping first.')
        used.add(pair)
        previous = next((v for v in (old or {}).get('equivalents', []) if (v['agent_type'], v['source_object'].casefold()) == pair), {})
        item['equivalents'].append(dict(agent_type=pair[0], source_object=obj.strip(),
                                       scope=previous.get('scope', 'provider-defined'), status=previous.get('status', 'manual')))
    with connection() as db:
        db.execute('BEGIN IMMEDIATE')
        current = db.execute('SELECT payload FROM fleet_entity_types WHERE owner=? AND id=?', (user, key)).fetchone()
        if (json.loads(current[0])['version'] if current else 0) != raw.get('version', 0):
            raise ValueError('This type changed. Reload before saving.')
        db.execute('INSERT INTO fleet_entity_types VALUES (?,?,?) ON CONFLICT(owner,id) DO UPDATE SET payload=excluded.payload', (user, key, json.dumps(item)))
    return item


def audit(db, user, action, records):
    identity = str(uuid.uuid4())
    db.execute('INSERT INTO fleet_entity_catalog_audit VALUES (?,?,?)', (user, identity,
               json.dumps(dict(action=action, created=now(), records=records))))
    return identity


def remove(user, key, replacement=None):
    types = definitions(user)
    if key not in types:
        raise ValueError('Entity type unavailable.')
    if types[key]['builtin']:
        raise ValueError('Built-in types can be hidden, but not removed.')
    if replacement and (replacement not in types or replacement == key):
        raise ValueError('Choose a different existing type for reassignment.')
    from modules.agents import entities
    with entities.connection():
        pass
    with connection() as db:
        db.execute('BEGIN IMMEDIATE')
        for candidate in [key] + ([replacement] if replacement else []):
            current = db.execute('SELECT payload FROM fleet_entity_types WHERE owner=? AND id=?', (user, candidate)).fetchone()
            if (json.loads(current[0])['version'] if current else 0) != types[candidate]['version']:
                raise ValueError('This type changed. Reload before removing it.')
        records = [json.loads(r[0]) for table, owner in [('fleet_entities', 'owner'), ('fleet_objects', 'user')]
                   for r in db.execute(f'SELECT payload FROM {table} WHERE {owner}=?', (user,))]
        if not replacement and (types[key]['equivalents'] or any(r.get('kind') == key for r in records)):
            raise ValueError('Reassign referenced objects and mappings before removing this type.')
        backups = [{'table': 'fleet_entity_types', 'id': key, 'payload': types[key]}]
        if replacement:
            target = types[replacement]
            backups.append(dict(table='fleet_entity_types', id=replacement, payload=target))
            target = {**target, 'equivalents': target['equivalents'] + types[key]['equivalents'], 'version': target['version'] + 1}
            db.execute('INSERT INTO fleet_entity_types VALUES (?,?,?) ON CONFLICT(owner,id) DO UPDATE SET payload=excluded.payload', (user, replacement, json.dumps(target)))
            for table, owner in [('fleet_entities', 'owner'), ('fleet_objects', 'user')]:
                for row in db.execute(f'SELECT id,payload FROM {table} WHERE {owner}=?', (user,)).fetchall():
                    value = json.loads(row['payload'])
                    if value.get('kind') != key:
                        continue
                    backups.append(dict(table=table, id=row['id'], payload=value))
                    db.execute(f'UPDATE {table} SET payload=? WHERE {owner}=? AND id=?', (json.dumps({**value, 'kind': replacement}), user, row['id']))
        identity = audit(db, user, 'remove type', backups)
        db.execute('DELETE FROM fleet_entity_types WHERE owner=? AND id=?', (user, key))
    return {'removed': key, 'audit_id': identity}


def cleanup(user):
    """Remove only truly blank, unreferenced placeholders; retain discovery history."""
    from modules.agents import entities
    with entities.connection():
        pass
    definitions(user)
    removed = []
    with connection() as db:
        db.execute('BEGIN IMMEDIATE')
        referenced = {r[0] for r in db.execute('SELECT source FROM fleet_entity_edges WHERE owner=? UNION SELECT target FROM fleet_entity_edges WHERE owner=? UNION SELECT source FROM fleet_entity_merges WHERE owner=? UNION SELECT target FROM fleet_entity_merges WHERE owner=?', (user,) * 4)}
        objects = [(r['id'], json.loads(r['payload'])) for r in db.execute('SELECT id,payload FROM fleet_objects WHERE user=?', (user,))]
        referenced.update(v.get('delegation_id') for _, v in objects if v.get('delegation_id'))
        for key, value in objects:
            if key in referenced or any(v for k, v in value.items() if k not in {'id', 'kind'}):
                continue
            removed.append(dict(table='fleet_objects', id=key, payload=value))
            db.execute('DELETE FROM fleet_objects WHERE user=? AND id=?', (user, key))
        for row in db.execute('SELECT id,payload FROM fleet_entities WHERE owner=?', (user,)).fetchall():
            value = json.loads(row['payload'])
            if row['id'] in referenced or any(v for k, v in value.items() if k not in {'id', 'kind'}):
                continue
            removed.append(dict(table='fleet_entities', id=row['id'], payload=value))
            db.execute('DELETE FROM fleet_entities WHERE owner=? AND id=?', (user, row['id']))
        used_kinds = {v.get('kind') for _, v in objects}
        used_kinds.update(json.loads(r[0]).get('kind') for r in db.execute('SELECT payload FROM fleet_entities WHERE owner=?', (user,)))
        for row in db.execute('SELECT id,payload FROM fleet_entity_types WHERE owner=?', (user,)).fetchall():
            value = json.loads(row['payload'])
            if row['id'] in defaults() or row['id'] in used_kinds or any(value.get(k) for k in ('name', 'description', 'keywords', 'equivalents')):
                continue
            removed.append(dict(table='fleet_entity_types', id=row['id'], payload=value))
            db.execute('DELETE FROM fleet_entity_types WHERE owner=? AND id=?', (user, row['id']))
        identity = audit(db, user, 'cleanup empty placeholders', removed)
    return {'removed': len(removed), 'audit_id': identity}
