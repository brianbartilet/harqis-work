"""Stable association between the private owner profile and a corpus entity."""
import json
from uuid import uuid4

from workflows.hfl.entity_store import get_store, identity_resolver


def owner_name():
    from modules.profile.store import get_profile_store
    profile = get_profile_store().get()
    return ' '.join(v.strip() for v in (profile.first_name, profile.last_name) if v.strip()) or profile.nickname.strip()


def needs_sync():
    name = owner_name()
    if not name:
        return False
    store = get_store()
    bound = store.state('owner-entity')
    return not bound or store.profiles().get(store.resolve(bound), {}).get('name') != name


def synchronize(available=None, chosen=None):
    name = owner_name()
    if not name:
        return {'id': None, 'candidates': []}
    store = get_store()
    available = available or {}
    with store.connection() as db:
        # Ordinary directory reads must not acquire a writer lock for an unchanged owner.
        bound = db.execute("SELECT value FROM state WHERE key='owner-entity'").fetchone()
        if bound and not chosen:
            identity = identity_resolver(db)(json.loads(bound[0]))
            previous = db.execute('SELECT data,kind FROM profiles WHERE id=?', (identity,)).fetchone()
            if previous and previous['kind'] == 'people' and json.loads(previous['data']).get('name') == name:
                return {'id': identity, 'name': name, 'candidates': []}
        db.execute('BEGIN IMMEDIATE')
        row = db.execute("SELECT value FROM state WHERE key='owner-entity'").fetchone()
        identity = identity_resolver(db)(json.loads(row[0])) if row else None
        candidates = [e for e in available.values() if e['kind'] == 'people' and e['label'].casefold() == name.casefold()]
        if chosen:
            if chosen not in {e['id'] for e in candidates}:
                raise ValueError('Choose a matching People entity')
            identity = chosen
        if not identity:
            if len(candidates) > 1:
                return {'id': None, 'candidates': candidates, 'name': name}
            identity = candidates[0]['id'] if candidates else 'manual-' + uuid4().hex
        previous = db.execute('SELECT data,kind FROM profiles WHERE id=?', (identity,)).fetchone()
        data = json.loads(previous[0]) if previous else dict(categories=[], aliases=[], partial_aliases=[], emails=[], phones=[], references=[], notes='')
        if data.get('name') != name or not previous or previous['kind'] != 'people':
            data['name'] = name
            db.execute('INSERT OR REPLACE INTO profiles(id,kind,data) VALUES (?,?,?)', (identity, 'people', json.dumps(data)))
        if not row or chosen:
            db.execute("INSERT OR REPLACE INTO state VALUES ('owner-entity',?)", (json.dumps(identity),))
        return {'id': identity, 'name': name, 'candidates': []}
