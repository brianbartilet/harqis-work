"""Canonical work projection, independent of graph display filters.

Spaces organize work; they never grant access. Canonical snapshot permission
filtering remains authoritative. Pins are commitments, not copies of actions.
"""
import json
from time import perf_counter
from urllib.parse import urlencode
from modules.agents import service, projection
from workflows.hfl.agent_fleet_store import FleetConflict, now


def state(user):
    with service.store().connect() as db:
        row = db.execute("SELECT version,payload FROM fleet_work_state WHERE user=?", (user,)).fetchone()
    return {'version': row['version'], 'pins': json.loads(row['payload'])} if row else {'version': 0, 'pins': []}


def pin(user, raw):
    from modules.hfl_corpus.ideas_api import canonical_snapshot
    identity = raw.get('id')
    if type(raw.get('pinned')) is not bool or type(raw.get('version')) is not int:
        raise ValueError('Provide a pin decision and current version.')
    if raw['pinned'] and not any(i['id'] == identity and i['status'] not in {'done', 'dismissed'} for i in canonical_snapshot()['actions']):
        raise ValueError('Choose an available open action.')
    with service.store().connect() as db:
        db.execute('BEGIN IMMEDIATE')
        row = db.execute('SELECT version,payload FROM fleet_work_state WHERE user=?', (user,)).fetchone()
        version, pins = (row['version'], json.loads(row['payload'])) if row else (0, [])
        if raw['version'] != version:
            raise FleetConflict('Focus changed in another view. Refresh before choosing again.')
        pins = [i for i in pins if i != identity]
        if raw['pinned']:
            if len(pins) >= 5:
                raise ValueError('Focus holds five commitments. Release one first.')
            pins.append(identity)
        db.execute('INSERT INTO fleet_work_state VALUES (?,?,?) ON CONFLICT(user) DO UPDATE SET version=excluded.version,payload=excluded.payload', (user, version + 1, json.dumps(pins)))
    return state(user)


def listing(user, offset=0, limit=40):
    from modules.hfl_corpus.ideas_api import canonical_snapshot
    from modules.hfl_corpus.workspace_views import listing as spaces
    from modules.hfl_corpus.action_agents import store
    from workflows.hfl.timeline_store import priority_key
    started = perf_counter()
    if offset < 0 or not 1 <= limit <= 100:
        raise ValueError('Use a nonnegative offset and limit from 1 to 100.')
    snapshot = canonical_snapshot(include_promoted=True)
    scope = spaces()
    active = set(scope['active'])
    agents = {a['id']: a for a in service.initialize().list() if projection.visible(a, user)}
    db = store()
    runs = db.list(limit=201)
    executions = {}
    for run in runs[:200]:
        aid = run['snapshot'].get('execution_settings', {}).get('fleet_agent', {}).get('id')
        if aid not in agents:
            continue
        identity = run['source_key'].partition(':')[2]
        executions.setdefault(identity, {'id': run['id'], 'agent_id': aid, 'state': run['state'], 'updated_at': run['updated_at'], 'url': '/hfl-corpus/actions?' + urlencode({'integration_agent': identity})})
    configs = db.configs()
    saved = state(user)
    rows = []
    for item in snapshot['actions']:
        if item['status'] in {'done', 'dismissed'} or (active and item.get('workspace_ids') and not active.intersection(item['workspace_ids'])):
            continue
        aid = configs.get('card:' + item['id'], {}).get('agent_id')
        execution = executions.get(item['id'])
        reasons = []
        if item['id'] in saved['pins']: reasons.append('Your commitment')
        if item.get('matrix') in {'Q1', 'Q2'}: reasons.append('Important (' + item['matrix'] + ')')
        if item.get('due_date'): reasons.append('Due ' + item['due_date'])
        if item.get('review_date'): reasons.append('Review ' + item['review_date'])
        attention = bool(execution and execution['state'] in {'review','failed','interrupted','awaiting_input','accepting'})
        rows.append({'id': 'action:' + item['id'], 'record_id': item['id'], 'kind': 'action', 'label': item['title'], 'record': item, 'goals':[{'id':g['id'],'title':g['title']} for g in snapshot.get('goals',[]) if 'action:'+item['id'] in g.get('linked_objects',[])], 'state': item['status'], 'agent_ids': [aid] if aid in agents else [], 'owner': agents[aid]['name'] if aid in agents else 'Unassigned', 'execution': execution, 'pinned': item['id'] in saved['pins'], 'attention': attention, 'reasons': reasons or ['No explicit priority set'], 'url': '/hfl-corpus/actions?' + urlencode({'edit': item['id'], 'edit_kind': 'actionable'})})
    rows.sort(key=lambda n: priority_key(n['record']))
    commitments = sorted((n for n in rows if n['pinned']), key=lambda n: saved['pins'].index(n['record_id']))
    attention = [n for n in rows if n['attention']]
    candidates = [n for n in rows if not n['pinned'] and not n['attention']]
    visible_ids = {n['record_id'] for n in rows}
    return {'items': rows[offset:offset+limit], 'commitments': commitments, 'attention': attention[:5], 'attention_total': len(attention), 'suggestions': candidates[:5], 'state': saved, 'outside_focus': [i for i in saved['pins'] if i not in visible_ids], 'agents': [{'id': a['id'], 'name': a['name']} for a in agents.values()], 'scope': {'active': scope['active'], 'revision': scope['preferences'].get('revision'), 'label': ' + '.join(v['name'] for v in scope['views'] if v['id'] in active) or 'All activity'}, 'coverage': {'actions': {'returned': len(rows[offset:offset+limit]), 'total': len(rows), 'has_more': offset+limit < len(rows), 'next_offset': offset+limit if offset+limit < len(rows) else None}, 'executions': {'returned': min(len(runs),200), 'limit':200, 'has_more':len(runs)>200, 'total':None}}, 'generated_at':now(), 'projection_ms':round((perf_counter()-started)*1000,1)}
