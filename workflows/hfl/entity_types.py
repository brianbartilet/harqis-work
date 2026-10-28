"""Persisted entity vocabulary shared by extraction and the directory."""
import re
import json

from workflows.hfl.entity_store import digest, get_store


RETIRED = frozenset({'topics'})


DEFAULTS = [
    ('people', 'People', '#ffbd91', 'Named people.'),
    ('companies', 'Organizations', '#deafff', 'Companies, nonprofits, government and educational institutions.'),
    ('tools', 'Tools', '#70edbd', 'Named software, products and tools.'),
    ('objects', 'Referenced objects', '#e9c96c', 'Qualified repository references; extracted deterministically.'),
    ('pets', 'Pets', '#f9a8d4', 'Named pets and companion animals. Do not classify their owners as pets.'),
]


def listing():
    defaults = [dict(id=k, name=n, color=c, description=d) for k, n, c, d in DEFAULTS]
    overrides = get_store().state('entity-type-overrides') or {}
    return [t for t in [overrides.get(t['id'], t) for t in defaults] +
            (get_store().state('custom-entity-types') or []) if t['id'] not in RETIRED]


def revision():
    return digest(listing())


def create(name, color, description):
    import json
    name, description = name.strip(), description.strip()
    identity = re.sub(r'[^a-z0-9]+', '-', name.casefold()).strip('-')
    if identity in RETIRED:
        raise ValueError('Topics has been retired; extract named entities instead.')
    if not identity or not name or not description or not re.fullmatch(r'#[0-9a-fA-F]{6}', color):
        raise ValueError('Enter a name, extraction description and a six-digit hex color.')
    with get_store().connection() as db:
        db.execute('BEGIN IMMEDIATE')
        row = db.execute("SELECT value FROM state WHERE key='custom-entity-types'").fetchone()
        custom = json.loads(row[0]) if row else []
        row = db.execute("SELECT value FROM state WHERE key='entity-type-overrides'").fetchone()
        overrides = json.loads(row[0]) if row else {}
        if identity in {r[0] for r in DEFAULTS} | {r['id'] for r in custom} or name.casefold() in {
                overrides.get(r[0], {}).get('name', r[1]).casefold() for r in DEFAULTS} | {r['name'].casefold() for r in custom}:
            raise ValueError('An entity type with this name already exists.')
        item = dict(id=identity, name=name, color=color.lower(), description=description)
        db.execute('INSERT OR REPLACE INTO state VALUES (?,?)', ('custom-entity-types', json.dumps(custom + [item])))
    return item


def update(identity, name, color, description):
    """Edit vocabulary properties without changing IDs or scheduling backfill."""
    name, description = name.strip(), description.strip()
    if not name or not description or not re.fullmatch(r'#[0-9a-fA-F]{6}', color):
        raise ValueError('Enter a name, extraction description and a six-digit hex color.')
    with get_store().connection() as db:
        db.execute('BEGIN IMMEDIATE')
        state = dict(db.execute("SELECT key,value FROM state WHERE key IN ('custom-entity-types','entity-type-overrides')"))
        custom = json.loads(state.get('custom-entity-types', '[]'))
        overrides = json.loads(state.get('entity-type-overrides', '{}'))
        defaults = [overrides.get(k, dict(id=k, name=n, color=c, description=d)) for k, n, c, d in DEFAULTS]
        types = defaults + custom
        if identity not in {t['id'] for t in types}:
            raise KeyError(identity)
        if any(t['id'] != identity and t['name'].casefold() == name.casefold() for t in types):
            raise ValueError('An entity type with this name already exists.')
        item = dict(id=identity, name=name, color=color.lower(), description=description)
        if identity in {t['id'] for t in defaults}:
            overrides[identity] = item
            key, value = 'entity-type-overrides', overrides
        else:
            key, value = 'custom-entity-types', [item if t['id'] == identity else t for t in custom]
        db.execute('INSERT OR REPLACE INTO state VALUES (?,?)', (key, json.dumps(value)))
    return item
