"""Owner commands for independent copies and live checklist entities."""
import copy
import json
import uuid

from fastapi import APIRouter, HTTPException, Request
from modules.hfl_corpus import timeline
from workflows.hfl.intent_reuse import copy_lists, list_entities, list_graph
from workflows.hfl.object_content import content_fields
from workflows.hfl.timeline_store import FIELDS, FollowUpConflict, isoformat


router = APIRouter(route_class=timeline.TimelineRoute)


def get_object(kind, identity):
    from modules.hfl_corpus import ideas_api as api
    if not isinstance(kind, str) or not isinstance(identity, str):
        raise HTTPException(422, 'Choose an action or idea.')
    collection = {'actionable': 'actions', 'idea': 'ideas'}.get(kind)
    if not collection:
        raise HTTPException(422, 'Choose an action or idea.')
    item = next((i for i in api.permitted_snapshot()[collection] if i['id'] == identity), None)
    if item is None:
        raise HTTPException(404, 'Object unavailable or protected.')
    return item

def receipt(db, raw, operation):
    key = str(uuid.UUID(str(raw.get('request_id', ''))))
    fingerprint = json.dumps([operation, raw], sort_keys=True)
    db.execute('CREATE TABLE IF NOT EXISTS intent_copy_requests (id TEXT PRIMARY KEY, fingerprint TEXT NOT NULL, payload TEXT NOT NULL)')
    previous = db.execute('SELECT * FROM intent_copy_requests WHERE id=?', (key,)).fetchone()
    if previous and previous['fingerprint'] != fingerprint:
        raise FollowUpConflict('This copy request was already used.')
    return key, fingerprint, json.loads(previous['payload']) if previous else None

@router.get('/reuse/options')
def options(request: Request, query: str = '', page: int = 1):
    from modules.hfl_corpus import ideas_api as api
    timeline.owner(request)
    if len(query) > 500:
        raise HTTPException(422, 'Use a search of at most 500 characters.')
    if page < 1:
        raise HTTPException(422, 'Choose a page greater than zero.')
    snapshot = api.permitted_snapshot()
    rows = [{**{k: i.get(k) for k in ('id', 'title', 'version', 'updated_at')}, 'kind': kind,
             'description': i.get('description') or i.get('body') or i.get('recommendation') or i.get('expected_outcome') or ''}
            for collection, kind in [('actions', 'actionable'), ('ideas', 'idea')] for i in snapshot[collection]]
    rows = sorted((i for i in rows if query.casefold() in (i['title'] + ' ' + i['description']).casefold()), key=lambda i: i.get('updated_at') or '', reverse=True)
    return {'items': rows[(page - 1) * 10:page * 10], 'total': len(rows), 'page': page}

@router.get('/reuse/board-ideas')
async def board_ideas(request: Request):
    from modules.hfl_corpus import ideas_api as api
    timeline.owner(request)
    from modules.hfl_corpus.action_scope import filter_actions
    items = api.permitted_snapshot()['ideas']
    if request.query_params.get('dismissed') != '1':
        items = [i for i in items if i['status'] != 'dismissed']
    return {'items': await filter_actions(request, items, api.store().followups)}

@router.get('/reuse/clone/{kind}/{identity}')
def clone_draft(request: Request, kind: str, identity: str):
    from modules.hfl_corpus import ideas_api as api
    timeline.owner(request)
    source = get_object(kind, identity)
    from modules.hfl_corpus.attachments import source_store
    fields = FIELDS if kind == 'actionable' else {'title', 'body', 'description', 'checklists', 'workspace_ids', 'expected_outcome', 'matrix', 'matrix_confidence', 'matrix_reason'}
    item = {k: copy.deepcopy(v) for k, v in source.items() if k in fields}
    titles = {i['title'] for i in api.permitted_snapshot()['actions' if kind == 'actionable' else 'ideas']}
    suffix = 1
    while source['title'][:185] + f' ({suffix})' in titles:
        suffix += 1
    item.update(title=source['title'][:185] + f' ({suffix})', checklists=copy_lists(source.get('checklists', []), reset=True))
    if kind == 'actionable':
        item.update(status='open', review_date='', due_date='', completion_note='', recurrence=None, agent_enabled=False)
    files, file_source = source_store(kind, identity)
    return {'item': item, 'source_version': source['version'], 'attachments': files.list(file_source)}

@router.post('/reuse/clone/{kind}/{identity}')
async def clone(request: Request, kind: str, identity: str):
    from modules.hfl_corpus import ideas_api as api
    actor = timeline.owner(request)
    raw = await timeline.body(request)
    source = get_object(kind, identity)
    allowed = FIELDS if kind == 'actionable' else {'title', 'body', 'description', 'checklists', 'workspace_ids', 'expected_outcome', 'matrix', 'matrix_confidence', 'matrix_reason', 'status'}
    if not isinstance(raw.get('item'), dict) or set(raw['item']) - allowed:
        raise HTTPException(422, 'Invalid clone fields.')
    canonical = api.store()
    from modules.hfl_corpus.attachments import source_store
    files, file_source = source_store(kind, identity)
    def save():
        with canonical.followups.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            key, fingerprint, previous = receipt(db, raw, ['clone', kind, identity])
            if previous:
                return previous
            current = canonical.followups.get(identity) if kind == 'actionable' else canonical.idea(identity)
            if current['version'] != raw.get('source_version'):
                raise FollowUpConflict('The source changed. Reopen the clone.')
            values = {**raw.get('item', {}), 'request_id': key}
            if kind == 'actionable':
                values.update(status='open', completion_note='', agent_enabled=False)
                item, _ = canonical.followups.create(values, actor=actor, connection=db)
            else:
                values.update(status='suggested')
                item = canonical.save_idea(values, actor, connection=db)
            files.clone(kind + ':' + identity, kind + ':' + item['id'], raw.get('attachments', []), db)
            prefix = 'action:' if kind == 'actionable' else 'idea:'
            db.execute('INSERT INTO idea_links VALUES (?,?,?,?)', (prefix + item['id'], prefix + identity, 'copied-from', isoformat()))
            result = {'item': item}
            db.execute('INSERT INTO intent_copy_requests VALUES (?,?,?)', (key, fingerprint, json.dumps(result)))
            return result
    return api.call(save)

@router.post('/reuse/copy-list')
async def copy_list(request: Request):
    from modules.hfl_corpus import ideas_api as api
    actor = timeline.owner(request)
    raw = await timeline.body(request)
    kind, identity = raw.get('kind'), raw.get('identity')
    get_object(kind, identity)
    checklist = api.call(content_fields, {'checklists': [raw.get('checklist')]})['checklists'][0]
    canonical = api.store()
    def save():
        with canonical.followups.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            key, fingerprint, previous = receipt(db, raw, 'copy-list')
            if previous:
                return previous
            target = canonical.followups.get(identity) if kind == 'actionable' else canonical.idea(identity)
            if target['version'] != raw.get('version'):
                raise FollowUpConflict('The destination changed. Search again before copying.')
            values = {'version': target['version'], 'checklists': target.get('checklists', []) + copy_lists([checklist])}
            item = canonical.followups.update(identity, values, actor=actor, connection=db) if kind == 'actionable' else canonical.save_idea(values, actor, identity, connection=db)
            result = {'item': item}
            db.execute('INSERT INTO intent_copy_requests VALUES (?,?,?)', (key, fingerprint, json.dumps(result)))
            return result
    return api.call(save)

@router.post('/maps/{identity}/paste')
async def paste_board(request: Request, identity: str):
    from modules.hfl_corpus import ideas_api as api
    actor = timeline.owner(request)
    raw = await timeline.body(request)
    canonical = api.store()
    if not isinstance(raw.get('source_board'), str):
        raise HTTPException(422, 'Choose a source board.')
    source = api.call(canonical.map, raw.get('source_board'))
    target = api.call(canonical.map, identity)
    selected = raw.get('selected')
    if not isinstance(selected, list) or not 1 <= len(selected) <= 200 or any(not isinstance(i, str) for i in selected) or len(set(selected)) != len(selected):
        raise HTTPException(422, 'Select 1–200 board objects.')
    snapshot = api.permitted_snapshot()
    lists = {i['id']: i for i in list_entities(snapshot)}
    shared = {prefix + i['id']: (kind, i) for collection, kind, prefix in [('actions', 'actionable', 'action:'), ('ideas', 'idea', 'idea:')] for i in snapshot[collection]}
    local = {i['id']: i for i in source['drafts']}
    thoughts = {n['id']: n for n in list_graph(snapshot)[0] if n['kind'] == 'thoughts' and n['list_id'] in source['members']}
    if any(i not in local and i not in thoughts and (i not in source['members'] or i not in shared and i not in lists) for i in selected):
        raise HTTPException(422, 'Copy is available for thoughts, lists, actions, and ideas only.')
    from modules.hfl_corpus.attachments import source_store
    file_stores = {i: source_store(shared[i][0], shared[i][1]['id']) for i in selected if i in shared}
    def save():
        with canonical.followups.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            key, fingerprint, previous = receipt(db, raw, ['paste', identity])
            if previous:
                return previous
            if canonical.map(identity)['version'] != raw.get('version') or canonical.map(source['id'])['version'] != raw.get('source_version'):
                raise FollowUpConflict('A board changed. Copy again before pasting.')
            mapping, drafts, members = {}, copy.deepcopy(target['drafts']), list(target['members'])
            names = {d['title'] for d in drafts} | {i['title'] for _, i in shared.values()} | {i['checklist']['title'] for i in lists.values()}
            positions = copy.deepcopy(target['positions'])
            def name(original):
                n = 1
                while original[:185] + f' ({n})' in names:
                    n += 1
                value = original[:185] + f' ({n})'
                names.add(value)
                return value
            for old_id in selected:
                if old_id in thoughts and thoughts[old_id]['list_id'] in selected:
                    continue  # Its copied list supplies the connected thought.
                if old_id in local or old_id in thoughts:
                    original = local.get(old_id) or {'title': thoughts[old_id]['label'], 'body': thoughts[old_id]['body']}
                    new_id = 'draft:' + uuid.uuid4().hex
                    drafts.append(dict(id=new_id, title=name(original['title']), body=original.get('body', '')))
                elif old_id in lists:
                    original = lists[old_id]
                    if original.get('owner_kind'):
                        owner = canonical.followups.get(original['owner_id']) if original['owner_kind'] == 'actionable' else canonical.idea(original['owner_id'])
                        revision = owner['version']
                    else:
                        revision = json.loads(db.execute('SELECT payload FROM intent_lists WHERE id=?', (old_id,)).fetchone()['payload'])['version']
                    if revision != original['version']:
                        raise FollowUpConflict('A copied list changed. Copy again.')
                    checklist = copy_lists([original['checklist']])[0]
                    checklist['title'] = name(checklist['title'])
                    new_id = 'list:' + uuid.uuid4().hex
                    db.execute('INSERT INTO intent_lists VALUES (?,?)', (new_id, json.dumps(dict(id=new_id, checklist=checklist, version=1, updated_at=isoformat()))))
                    members.append(new_id)
                else:
                    kind, original = shared[old_id]
                    current = canonical.followups.get(original['id']) if kind == 'actionable' else canonical.idea(original['id'])
                    if current['version'] != original['version']:
                        raise FollowUpConflict('A copied object changed. Copy again.')
                    allowed = FIELDS if kind == 'actionable' else {'title', 'body', 'description', 'checklists', 'workspace_ids', 'expected_outcome', 'matrix', 'matrix_confidence', 'matrix_reason'}
                    values = {k: copy.deepcopy(v) for k, v in original.items() if k in allowed}
                    values.update(title=name(original['title']), request_id=str(uuid.uuid4()), checklists=copy_lists(original.get('checklists', []), reset=True))
                    if kind == 'actionable':
                        values.update(status='open', review_date='', due_date='', recurrence=None, completion_note='', agent_enabled=False)
                        item, _ = canonical.followups.create(values, actor=actor, connection=db)
                    else:
                        item = canonical.save_idea(values, actor, connection=db)
                    new_id = ('action:' if kind == 'actionable' else 'idea:') + item['id']
                    files, file_source = file_stores[old_id]
                    attachment_ids = [r['id'] for r in db.execute('SELECT id FROM input_attachments WHERE source=? AND detached=0', (file_source,))]
                    files.clone(file_source, kind + ':' + item['id'], attachment_ids, db)
                    db.execute('INSERT INTO idea_links VALUES (?,?,?,?)', (new_id, old_id, 'copied-from', isoformat()))
                    members.append(new_id)
                mapping[old_id] = new_id
                point = source['positions'].get(old_id, {'x': 0, 'y': 0})
                positions[new_id] = {axis: point[axis] + 40 for axis in ('x', 'y')}
            edges = target['edges'] + [{**edge, 'source': mapping[edge['source']], 'target': mapping[edge['target']]} for edge in source['edges'] if edge['source'] in mapping and edge['target'] in mapping]
            item = canonical.save_map(dict(version=target['version'], members=members, drafts=drafts, edges=edges, positions=positions), identity, connection=db)
            result = {'item': item, 'mapping': mapping}
            db.execute('INSERT INTO intent_copy_requests VALUES (?,?,?)', (key, fingerprint, json.dumps(result)))
            return result
    return api.call(save)

@router.get('/lists/{identity:path}')
def get_list(request: Request, identity: str):
    timeline.owner(request)
    return {'item': require_list(identity)}

def require_list(identity):
    from modules.hfl_corpus import ideas_api as api
    item = next((i for i in list_entities(api.permitted_snapshot()) if i['id'] == identity), None)
    if item is None:
        raise HTTPException(404, 'List unavailable or protected.')
    return item

@router.post('/lists')
@router.patch('/lists/{identity:path}')
async def save_list(request: Request, identity: str | None = None):
    from modules.hfl_corpus import ideas_api as api
    actor = timeline.owner(request)
    raw = await timeline.body(request)
    checklist = api.call(content_fields, {'checklists': [raw.get('checklist')]})['checklists'][0]
    canonical = api.store()
    previous = require_list(identity) if identity else None
    if previous and previous.get('owner_kind'):
        kind, owner_id = previous['owner_kind'], previous['owner_id']
        owner = get_object(kind, owner_id)
        if raw.get('version') != owner['version']:
            raise HTTPException(409, 'The list changed. Reopen before saving.')
        checklist['id'] = previous['checklist']['id']
        values = {'version': owner['version'], 'checklists': [checklist if c['id'] == checklist['id'] else c for c in owner['checklists']]}
        if kind == 'actionable':
            api.call(canonical.followups.update, owner_id, values, actor=actor)
        else:
            api.call(canonical.save_idea, values, actor, owner_id)
    else:
        identity = identity or 'list:' + str(api.call(uuid.UUID, raw.get('request_id', '')))
        with canonical.followups.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            found = db.execute('SELECT payload FROM intent_lists WHERE id=?', (identity,)).fetchone()
            old = json.loads(found['payload']) if found else None
            if old and raw.get('version') != old['version']:
                if not previous and old['checklist'] == checklist:
                    return {'item': old}
                raise HTTPException(409, 'The list changed. Reopen before saving.')
            item = dict(id=identity, checklist=checklist, version=(old['version'] if old else 0) + 1, updated_at=isoformat())
            db.execute('INSERT INTO intent_lists VALUES (?,?) ON CONFLICT(id) DO UPDATE SET payload=excluded.payload', (identity, json.dumps(item)))
    return {'item': require_list(identity)}
