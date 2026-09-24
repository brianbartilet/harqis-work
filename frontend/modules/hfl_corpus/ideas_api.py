"""Canonical owner commands for ideas, mind maps, and durable graph links."""
import copy
import json
import os
import uuid

import httpx
from fastapi import APIRouter, HTTPException, Request, UploadFile, File
from fastapi.responses import FileResponse
from starlette.concurrency import run_in_threadpool

from modules.hfl_corpus import timeline
from workflows.hfl.ideas_store import IdeasStore
from workflows.hfl.timeline_store import FollowUpConflict, FIELDS, isoformat

router = APIRouter(prefix='/ideas', route_class=timeline.TimelineRoute)


def store():
    return IdeasStore(timeline.store())


def call(operation, *args, **kwargs):
    try:
        return operation(*args, **kwargs)
    except FollowUpConflict as exc:
        raise HTTPException(409, str(exc)) from None
    except KeyError:
        raise HTTPException(404, 'Object not found.') from None
    except (ValueError, TypeError) as exc:
        raise HTTPException(422, str(exc)) from None


def canonical_snapshot():
    from config import get_settings
    settings = get_settings()
    if settings.hfl_corpus_api_url and os.getenv('HFL_TIMELINE_LOCAL_PREVIEW') != '1':
        try:
            response = httpx.get(settings.hfl_corpus_api_url.rstrip('/') + '/api/hfl/timeline/ideas/snapshot',
                                headers={'Authorization': 'Bearer ' + settings.hfl_corpus_api_token}, timeout=45)
            response.raise_for_status()
            return response.json()
        except (httpx.HTTPError, ValueError):
            raise HTTPException(502, 'Ideas and actions could not load from the canonical host.') from None
    return permitted_snapshot()


def permitted_snapshot(entries=None):
    from modules.hfl_corpus.entities import current_entries
    data = store().snapshot()
    # The same permitted corpus projection gates graph and brainstorming context.
    entries = current_entries() if entries is None else entries
    graph_ids = {(e['path'], key): 'entry:' + e['id'] for e in entries for key in (e['id'], timeline.entry_evidence_id(e['text']))}
    memory_ids = {timeline.entry_evidence_id(e['text']): 'entry:' + e['id'] for e in entries}
    data['memories'] = [{**m, 'graph_entry_id': memory_ids[m['entry_id']]}
                        for m in data.get('memories', []) if m['entry_id'] in memory_ids]
    def reference_key(ref):
        return (ref.get('path'), ref.get('entry_id'))
    for kind in ('ideas', 'actions'):
        data[kind] = [i for i in data[kind] if (not i.get('source') or reference_key(i['source']) in graph_ids)
                      and all(reference_key(ref) in graph_ids for ref in i.get('evidence', []) if isinstance(ref, dict) and ref.get('entry_id'))]
        for item in data[kind]:
            item['graph_source_id'] = graph_ids.get(reference_key(item.get('source') or {}), '')
            item['graph_evidence_ids'] = list(dict.fromkeys(graph_ids[reference_key(ref)] for ref in item.get('evidence', []) if isinstance(ref, dict) and reference_key(ref) in graph_ids))
    return data


def require_idea(identity):
    item = next((i for i in permitted_snapshot()['ideas'] if i['id'] == identity), None)
    if item is None:
        raise HTTPException(404, 'Idea unavailable or protected.')
    return item


def catalogue():
    from modules.hfl_corpus.entities import graph
    return {n['id']: n for n in graph(limit=0)['nodes']}


def check_node(identity, available=None):
    if not isinstance(identity, str) or not 1 <= len(identity) <= 200:
        raise HTTPException(422, 'Choose a valid object ID.')
    available = catalogue() if available is None else available
    if identity not in available:
        # Dates can have manually captured ideas even without corpus entries.
        if isinstance(identity, str) and identity.startswith('daily:'):
            from datetime import date
            call(date.fromisoformat, identity[6:])
            return {'id': identity, 'kind': 'daily', 'label': identity[6:]}
        raise HTTPException(404, 'Connection is unavailable or protected.')
    return available[identity]


@router.get('/snapshot')
def snapshot(request: Request):
    timeline.owner(request)
    return permitted_snapshot()


@router.get('/connection-availability')
def connection_availability(request: Request):
    timeline.owner(request)
    from modules.hfl_corpus.entities import graph
    from modules.hfl_corpus.action_connections import connected_actions
    return {'action_ids': connected_actions(graph(limit=0), store().maps())}


@router.get('/actions/{identity}/connections')
def action_connections(request: Request, identity: str):
    return object_connections(request, identity, kind='action')


@router.get('/dates/{identity}/connections')
def date_connections(request: Request, identity: str):
    from datetime import date
    identity = call(date.fromisoformat, identity).isoformat()
    return object_connections(request, identity, kind='daily')


def object_connections(request: Request, identity: str, *, kind: str):
    timeline.owner(request)
    from modules.hfl_corpus.entities import graph
    from modules.hfl_corpus.action_connections import project
    from services.markdown import render_markdown
    data = project(identity, graph(limit=0), store().maps(), kind=kind)
    for node in data['nodes']:
        node['body_html'] = str(render_markdown(node.get('body') or node.get('description') or ''))
    return data


@router.get('/boards')
def boards(request: Request):
    """Board metadata and Goals never require a corpus scan."""
    timeline.owner(request)
    canonical = store()
    from workflows.hfl.colors import PIN_COLORS
    return {'maps': canonical.maps(), 'goals': canonical.goals(), 'palette': list(PIN_COLORS)}


@router.put('/boards/order')
async def reorder_boards(request: Request):
    timeline.owner(request)
    raw = await timeline.body(request)
    await run_in_threadpool(call, store().reorder_boards, raw.get('ids'))
    return {'saved': True}


@router.put('/goals/order')
async def reorder_goals(request: Request):
    timeline.owner(request)
    raw = await timeline.body(request)
    await run_in_threadpool(call, store().reorder_goals, raw.get('ids'))
    return {'saved': True}


def goal_choices(identities=None):
    # Resolve only intent records; manual objects need no corpus/entity scan.
    from modules.hfl_corpus.entities import current_entries
    canonical = store()
    data = {'ideas': canonical.ideas(), 'actions': canonical.followups.list() + canonical.followups.list(closed=True)}
    if identities is not None:
        data = {kind: [item for item in data[kind] if prefix + item['id'] in identities]
                for kind, prefix in [('ideas', 'idea:'), ('actions', 'action:')]}
    def references(item):
        return [ref for ref in [item.get('source'), *item.get('evidence', [])]
                if isinstance(ref, dict) and ref.get('entry_id')]
    needs_corpus = any(item.get('source') or references(item) for items in data.values() for item in items)
    permitted = {(e['path'], key) for e in current_entries()
                 for key in (e['id'], timeline.entry_evidence_id(e['text']))} if needs_corpus else set()
    return {prefix + item['id']: {'id': prefix + item['id'], 'kind': kind, 'label': item['title']}
            for kind, prefix in [('ideas', 'idea:'), ('actions', 'action:')]
            for item in data[kind]
            if not item.get('source') or (item['source'].get('path'), item['source'].get('entry_id')) in permitted
            if all((ref.get('path'), ref['entry_id']) in permitted for ref in references(item))}


@router.get('/goal-options')
def goal_options(request: Request):
    timeline.owner(request)
    return {'nodes': list(goal_choices().values())}


@router.get('/maps/{identity}')
def get_board(request: Request, identity: str):
    timeline.owner(request)
    return {'item': call(store().map, identity)}


@router.get('/maps/{identity}/graph')
def board_graph(request: Request, identity: str):
    timeline.owner(request)
    board = call(store().map, identity)
    if not board['members']:
        return {'nodes': [], 'edges': [], 'sources': []}
    # Permission checks remain authoritative for shared objects. Draft-only
    # boards bypass corpus loading entirely; editing uses the browser cache.
    from modules.hfl_corpus.entities import graph
    shared = graph(limit=0)
    available = {n['id']: n for n in shared['nodes']}
    members = set(board['members'])
    members.update(n['id'] for n in shared['nodes'] if n.get('list_id') in members and n['id'] not in board.get('hidden_members', []))
    return {'nodes': [available[i] for i in members if i in available],
            'edges': [e for e in shared['edges'] if e['source'] in members and e['target'] in members
                      and e['source'] in available and e['target'] in available], 'sources': []}


@router.get('/maps/{identity}/attach-options')
def attach_options(request: Request, identity: str, query: str = '', offset: int = 0):
    timeline.owner(request)
    board = call(store().map, identity)
    if offset < 0 or len(query) > 500:
        raise HTTPException(422, 'Invalid search or page.')
    from modules.hfl_corpus.board_choices import catalogue as attachment_catalogue
    excluded = set(board['members']) | {'board:' + identity}
    matching = [n for n in attachment_catalogue().values() if n['id'] not in excluded
                and query.casefold() in (n['label'] + ' ' + n['kind']).casefold()]
    matching.sort(key=lambda n: (n['updated_at'], n['id']), reverse=True)
    return {'nodes': matching[offset:offset + 50], 'total': len(matching),
            'has_more': offset + 50 < len(matching)}


@router.post('/render')
async def render_body(request: Request):
    timeline.owner(request)
    from services.markdown import render_markdown
    raw = await timeline.body(request)
    body = raw.get('body', '')
    if not isinstance(body, str) or len(body) > 60000:
        raise HTTPException(422, 'Markdown is too long.')
    return {'html': str(render_markdown(body))}


@router.get('/objects/{identity}')
def idea(request: Request, identity: str):
    timeline.owner(request)
    from services.markdown import render_markdown
    item = require_idea(identity)
    return {'item': item, 'body_html': str(render_markdown(item.get('body', '')))}


async def validate_source(raw):
    if raw.get('source'):
        source = raw['source']
        if not isinstance(source, dict):
            raise HTTPException(422, 'Invalid source evidence.')
        await timeline.evidence(source.get('path'), source.get('entry_id'))


@router.post('/objects')
async def create_idea(request: Request):
    actor = timeline.owner(request)
    raw = await timeline.body(request)
    await validate_source(raw)
    return {'item': call(store().save_idea, raw, actor)}


@router.patch('/objects/{identity}')
async def edit_idea(request: Request, identity: str):
    actor = timeline.owner(request)
    require_idea(identity)
    raw = await timeline.body(request)
    await validate_source(raw)
    return {'item': call(store().save_idea, raw, actor, identity)}


@router.post('/topics')
async def create_topic(request: Request):
    actor = timeline.owner(request)
    from modules.hfl_corpus.entities import is_link
    raw = await timeline.body(request)
    if isinstance(raw.get('label'), str) and is_link(raw['label']):
        raise HTTPException(422, 'Use a topic name, not a URL.')
    item = call(store().topic, raw.get('label'))
    from workflows.hfl.entity_store import get_store
    entities = get_store()
    if item['id'] not in entities.profiles():
        call(entities.save_profile, item['id'], 'topics', {'name': item['label'], 'categories': [], 'emails': [], 'phones': [], 'references': [], 'notes': ''}, actor)
    return {'item': item}


@router.post('/links')
@router.delete('/links')
async def link(request: Request):
    timeline.owner(request)
    raw = await timeline.body(request)
    available = catalogue()
    check_node(raw.get('source'), available)
    check_node(raw.get('target'), available)
    call(store().link, raw['source'], raw['target'], raw.get('relation', 'related-to'), request.method == 'DELETE')
    return {'saved': True}


@router.post('/maps')
@router.patch('/maps/{identity}')
async def save_map(request: Request, identity: str | None = None):
    timeline.owner(request)
    raw = await timeline.body(request)
    previous = call(store().map, identity) if identity else {}
    if 'members' in raw and (not isinstance(raw['members'], list) or len(raw['members']) > 10000):
        raise HTTPException(422, 'Choose a valid membership list.')
    available = None
    for member in raw.get('members', []):
        if member not in previous.get('members', []):
            if isinstance(member, str) and member.startswith('goal:'):
                await run_in_threadpool(call, store().goal, member[5:])
                continue
            if available is None:
                from modules.hfl_corpus.board_choices import catalogue as attachment_catalogue
                available = await run_in_threadpool(attachment_catalogue)
            check_node(member, available)
    return {'item': call(store().save_map, raw, identity)}


@router.delete('/maps/{identity}')
async def delete_board(request: Request, identity: str):
    timeline.owner(request)
    raw = await timeline.body(request)
    await run_in_threadpool(call, store().delete_board, identity, raw.get('version'))
    return {'deleted': True}


@router.post('/maps/{identity}/promote')
async def promote(request: Request, identity: str):
    actor = timeline.owner(request)
    raw = await timeline.body(request)
    if not isinstance(raw.get('draft_id'), str):
        raise HTTPException(422, 'Choose a draft thought.')
    return call(store().promote_draft, identity, raw['draft_id'], raw.get('version'), actor)


@router.get('/goals/{identity}')
def get_goal(request: Request, identity: str):
    timeline.owner(request)
    return {'item': call(store().goal, identity)}


@router.post('/maps/{identity}/promote-link')
async def promote_connection(request: Request, identity: str):
    timeline.owner(request)
    raw = await timeline.body(request)
    edge = raw.get('edge')
    if not isinstance(edge, dict) or set(edge) - {'source', 'target', 'relation'}:
        raise HTTPException(422, 'Choose a board connection.')
    relation = edge.get('relation', 'related-to')
    if not isinstance(relation, str) or relation not in {'related-to', 'supports', 'alternative', 'depends-on'}:
        raise HTTPException(422, 'Choose a supported relationship.')
    available = catalogue()
    check_node(edge.get('source'), available)
    check_node(edge.get('target'), available)
    return {'item': call(store().promote_connection, identity, edge, raw.get('version'))}


@router.post('/maps/{identity}/connections')
async def edit_board_connection(request: Request, identity: str):
    timeline.owner(request)
    raw = await timeline.body(request)
    return {'item': await run_in_threadpool(call, store().edit_connection, identity, raw)}


@router.post('/goals')
@router.patch('/goals/{identity}')
async def save_goal(request: Request, identity: str | None = None):
    actor = timeline.owner(request)
    raw = await timeline.body(request)
    return await run_in_threadpool(save_goal_values, raw, actor, identity)


def save_goal_values(raw, actor, identity=None):
    """Only linked references need corpus validation; never block the event loop."""
    available = None
    links = raw.get('linked_objects', [])
    if not isinstance(links, list):
        raise HTTPException(422, 'Invalid Goal links.')
    requested = list(links)
    for milestone in raw.get('milestones', []) if isinstance(raw.get('milestones', []), list) else []:
        if isinstance(milestone, dict) and isinstance(milestone.get('actions', []), list):
            requested.extend(milestone.get('actions', []))
    for link in links:
        if available is None:
            available = goal_choices(requested)
        if check_node(link, available)['kind'] not in {'ideas', 'actions'}:
            raise HTTPException(422, 'Link Goals to Ideas or Actions.')
    for milestone in raw.get('milestones', []) if isinstance(raw.get('milestones', []), list) else []:
        if not isinstance(milestone, dict):
            raise HTTPException(422, 'Invalid milestone.')
        actions = milestone.get('actions', [])
        if not isinstance(actions, list):
            raise HTTPException(422, 'Invalid milestone actions.')
        for action in actions:
            if available is None:
                available = goal_choices(requested)
            node = check_node(action, available)
            if node['kind'] != 'actions':
                raise HTTPException(422, 'Milestones link to actions.')
    return {'item': call(store().save_goal, raw, actor, identity)}


@router.get('/objects/{identity}/conversion')
def conversion(request: Request, identity: str, checklist_id: str = '', item_id: str = ''):
    timeline.owner(request)
    item = require_idea(identity)
    from modules.hfl_corpus.attachments import source_store
    files, source = source_store('idea', identity)
    fields = {k: copy.deepcopy(item[k]) for k in FIELDS if k in item and k not in {'status', 'prompt', 'agent_enabled', 'completion_note', 'due_date', 'review_date'}}
    fields.setdefault('expected_outcome', (item.get('recommendation') or item.get('body') or item.get('description') or item['title'])[:3000])
    for checklist in fields.get('checklists', []):
        for task in checklist['items']:
            task['done'] = False
    if checklist_id or item_id:
        task = checklist_task(item, checklist_id, item_id)
        fields.update(title=task['text'][:200], expected_outcome=task['text'], checklists=[])
    return {'item': fields, 'idea_version': item['version'], 'attachments': files.list(source), 'checklist_id': checklist_id, 'item_id': item_id}


def checklist_task(idea, checklist_id, item_id):
    for checklist in idea.get('checklists', []):
        if checklist['id'] == checklist_id:
            for item in checklist['items']:
                if item['id'] == item_id:
                    return item
    raise HTTPException(409, 'The checklist item changed or was removed. Reopen the idea.')


@router.post('/objects/{identity}/convert')
async def convert(request: Request, identity: str):
    actor = timeline.owner(request)
    original = require_idea(identity)
    raw = await timeline.body(request)
    from modules.hfl_corpus.attachments import source_store
    files, source = source_store('idea', identity)
    fields = raw.get('item', {})
    if not isinstance(fields, dict):
        raise HTTPException(422, 'Invalid action draft.')
    request_id = call(lambda: str(uuid.UUID(raw.get('request_id', ''))))
    attachment_ids = raw.get('attachments', [])
    if not isinstance(attachment_ids, list) or any(not isinstance(i, str) for i in attachment_ids):
        raise HTTPException(422, 'Choose valid attachment IDs.')
    checklist_id, item_id = raw.get('checklist_id', ''), raw.get('item_id', '')
    fingerprint_parts = [identity, fields, sorted(attachment_ids)]
    if checklist_id or item_id:
        if not isinstance(checklist_id, str) or not isinstance(item_id, str):
            raise HTTPException(422, 'Invalid checklist identity.')
        fingerprint_parts.extend([checklist_id, item_id])
    fingerprint = json.dumps(fingerprint_parts, sort_keys=True)
    canonical = store()
    # Byte validation and ownership cloning happen before committing the action.
    with canonical.followups.connect() as db:
        db.execute('BEGIN IMMEDIATE')
        existing = db.execute('SELECT payload FROM followups WHERE request_id=?', (request_id,)).fetchone()
        if existing:
            action = json.loads(existing['payload'])
            receipt = db.execute('SELECT fingerprint FROM idea_conversions WHERE request_id=?', (request_id,)).fetchone()
            if receipt and receipt['fingerprint'] != fingerprint:
                raise HTTPException(409, 'This conversion was already saved with different content. Open the action to edit it.')
            linked = db.execute("SELECT 1 FROM idea_links WHERE source=? AND target=? AND relation='develops-into'", ('idea:' + identity, 'action:' + action['id'])).fetchone()
            if not linked:
                raise HTTPException(409, 'This request was already used for a different action.')
            return {'item': action, 'duplicate': True}
        current = canonical.idea(identity)
        if current['version'] != raw.get('idea_version'):
            raise HTTPException(409, 'The idea changed. Reopen the conversion draft.')
        if current['status'] == 'dismissed':
            raise HTTPException(409, 'Restore this idea before creating an action.')
        if checklist_id or item_id:
            checklist_task(current, checklist_id, item_id)
        action, _ = call(canonical.followups.create, {**fields, 'request_id': request_id, 'agent_enabled': False},
                         actor=actor, source=original.get('source'), connection=db)
        db.execute('INSERT INTO idea_conversions VALUES (?,?)', (request_id, fingerprint))
        call(files.clone, source, 'actionable:' + action['id'], attachment_ids, db)
        if checklist_id or item_id:
            db.execute('INSERT INTO idea_item_actions VALUES (?,?,?,?)', (identity, checklist_id, item_id, action['id']))
        target = 'action:' + action['id']
        db.execute('INSERT INTO idea_links VALUES (?,?,?,?)', ('idea:' + identity, target, 'develops-into', isoformat()))
        for row in db.execute('SELECT * FROM idea_links WHERE source=? OR target=?', ('idea:' + identity, 'idea:' + identity)).fetchall():
            other = row['target'] if row['source'] == 'idea:' + identity else row['source']
            if other.startswith(('entry:', 'entity:', 'daily:')):
                db.execute('INSERT OR IGNORE INTO idea_links VALUES (?,?,?,?)', (target, other, 'context', isoformat()))
        current.update(status='adopted', version=current['version'] + 1, updated_at=isoformat())
        db.execute('INSERT INTO idea_edits VALUES (?,?,?) ON CONFLICT(id) DO UPDATE SET version=excluded.version,payload=excluded.payload', (identity, current['version'], json.dumps(current)))
        db.execute('INSERT INTO idea_history VALUES (?,?,?,?)', (identity, current['version'], str(actor), json.dumps(current)))
        db.execute("UPDATE timeline_suggestions SET status='adopted',followup_id=? WHERE id=?", (action['id'], identity))
    return {'item': action}


@router.get('/objects/{identity}/attachments')
@router.get('/objects/{identity}/attachments/{attachment_id}')
def attachments(request: Request, identity: str, attachment_id: str | None = None):
    timeline.owner(request)
    require_idea(identity)
    from modules.hfl_corpus.attachments import source_store
    files, source = source_store('idea', identity)
    if attachment_id:
        manifest = files.get(source, attachment_id)
        return FileResponse(files.path(manifest), filename=manifest['name'], media_type='application/octet-stream')
    return {'attachments': files.list(source)}


@router.post('/objects/{identity}/attachments')
async def upload(request: Request, identity: str, files: list[UploadFile] = File(...)):
    timeline.owner(request)
    require_idea(identity)
    from modules.hfl_corpus.attachments import source_store
    target, source = source_store('idea', identity)
    return {'attachments': await target.upload(source, files)}


@router.delete('/objects/{identity}/attachments/{attachment_id}')
def detach(request: Request, identity: str, attachment_id: str):
    timeline.owner(request)
    require_idea(identity)
    from modules.hfl_corpus.attachments import source_store
    files, source = source_store('idea', identity)
    files.detach(source, attachment_id)
    return {'attachments': files.list(source)}


def save_proposal(identity, raw, actor):
    canonical = store()
    board = call(canonical.map, identity)
    parents = raw.get('parents', [])
    local_ids = {d['id'] for d in board['drafts']}
    available = catalogue()
    if not isinstance(parents, list) or len(parents) > 5 or any(not isinstance(p, str) for p in parents):
        raise HTTPException(422, 'A proposal can have up to five parents.')
    for parent in parents:
        if parent not in local_ids:
            check_node(parent, available)
        if parent not in board['members'] and parent not in local_ids:
            raise HTTPException(409, 'A proposal parent was removed from the board.')
    values = raw.get('item', {})
    if not isinstance(values, dict) or set(values) - {'title', 'description', 'body'}:
        raise HTTPException(422, 'Invalid proposed thought.')
    node = 'draft:' + call(lambda: str(uuid.UUID(raw.get('request_id', ''))))
    existing = next((d for d in board['drafts'] if d['id'] == node), None)
    if existing:
        return {'item': existing}
    promoted = 'idea:idea-' + str(uuid.uuid5(uuid.NAMESPACE_URL, identity + ':' + node))
    if promoted in board['members'] or canonical.promoted_idea(identity, node):
        return {'item': {'id': promoted, 'title': values.get('title', '')}}
    from workflows.hfl.object_content import consolidated_description
    draft = {'id': node, 'title': values.get('title'), 'body': consolidated_description(values)}
    call(canonical.save_map, {'version': board['version'], 'drafts': [*board['drafts'], draft],
                             'edges': [*board['edges'], *[{'source': p, 'target': node, 'relation': 'related-to'} for p in parents]]}, identity)
    return {'item': draft}


@router.post('/maps/{identity}/accept-proposal')
async def accept_proposal(request: Request, identity: str):
    actor = timeline.owner(request)
    return save_proposal(identity, await timeline.body(request), actor)

from modules.hfl_corpus.intent_reuse import register as register_reuse
register_reuse(router)
