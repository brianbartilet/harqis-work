"""Persisted entity vocabulary shared by extraction and the directory."""
import re

from workflows.hfl.entity_store import digest, get_store


DEFAULTS = [
    ('people', 'People', '#ffbd91', 'Named people.'),
    ('companies', 'Organizations', '#deafff', 'Companies, nonprofits, government and educational institutions.'),
    ('tools', 'Tools', '#70edbd', 'Named software, products and tools.'),
    ('topics', 'Topics', '#9bafff', 'Substantive topics and concepts.'),
    ('objects', 'Referenced objects', '#e9c96c', 'Qualified repository references; extracted deterministically.'),
    ('pets', 'Pets', '#f9a8d4', 'Named pets and companion animals. Do not classify their owners as pets.'),
]


def listing():
    defaults = [dict(id=k, name=n, color=c, description=d) for k, n, c, d in DEFAULTS]
    return defaults + (get_store().state('custom-entity-types') or [])


def revision():
    return digest(listing())


def create(name, color, description):
    import json
    name, description = name.strip(), description.strip()
    identity = re.sub(r'[^a-z0-9]+', '-', name.casefold()).strip('-')
    if not identity or not name or not description or not re.fullmatch(r'#[0-9a-fA-F]{6}', color):
        raise ValueError('Enter a name, extraction description and a six-digit hex color.')
    with get_store().connection() as db:
        db.execute('BEGIN IMMEDIATE')
        row = db.execute("SELECT value FROM state WHERE key='custom-entity-types'").fetchone()
        custom = json.loads(row[0]) if row else []
        if identity in {r[0] for r in DEFAULTS} | {r['id'] for r in custom} or name.casefold() in {
                r[1].casefold() for r in DEFAULTS} | {r['name'].casefold() for r in custom}:
            raise ValueError('An entity type with this name already exists.')
        item = dict(id=identity, name=name, color=color.lower(), description=description)
        db.execute('INSERT OR REPLACE INTO state VALUES (?,?)', ('custom-entity-types', json.dumps(custom + [item])))
    return item
