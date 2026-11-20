"""Authenticated fleet CRUD, assets, sessions and presentation graph."""
import io
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import Response, StreamingResponse
from PIL import Image
from modules.hfl_corpus.agent_bridge import owner_auth
from modules.hfl_shares.security import make_csrf_token
from modules.agents import service
from workflows.hfl.agent_fleet_store import FleetConflict
from web import templates, page_context, require_user

router = APIRouter(prefix='/agents')
api = APIRouter(prefix='/api', dependencies=[Depends(owner_auth)])


def checked(fn, *args, **kwargs):
    try:
        return fn(*args, **kwargs)
    except FleetConflict as exc:
        raise HTTPException(409, str(exc)) from None
    except KeyError:
        raise HTTPException(404, 'Agent or attachment unavailable.') from None
    except (ValueError, TypeError) as exc:
        raise HTTPException(422, str(exc)) from None


@router.get('')
def page(request: Request):
    user, redirect = require_user(request)
    if redirect:
        return redirect
    from modules.second_brain import hud
    from datetime import datetime
    from zoneinfo import ZoneInfo
    return templates.TemplateResponse(request, 'modules/agents/index.html', page_context(
        request, user, 'agents', csrf=make_csrf_token(user), memory_csrf=make_csrf_token(user),
        today_iso=datetime.now(ZoneInfo('Asia/Singapore')).date().isoformat(), entry_source_options=['manual-entry'],
        hud_sizes=hud.SIZES, hud_colors=hud.PIN_COLORS, hud_catalog=hud.inventory()))


@api.get('/catalogue')
def catalogue(user=Depends(owner_auth)):
    from modules.agents.availability import for_agent
    data = service.catalogue()
    for item in data['services']:
        item['availability'] = for_agent(user, {**service.defaults(), 'runtime': item['id']})
    return data


@api.get('/specialists')
def specialist_catalogue():
    from modules.agents import specialists
    return {'items': checked(specialists.catalog)}


@api.get('/profile-sources')
def profile_sources():
    from modules.agents import profile_sources as sources
    return {'items':checked(sources.sources)}


@api.post('/profile-sources')
def add_profile_source(raw: dict):
    from modules.agents import profile_sources as sources
    return {'item':checked(sources.save,raw)}


@api.post('/profile-sources/{identity}')
def edit_profile_source(identity: str,raw: dict):
    from modules.agents import profile_sources as sources
    return {'item':checked(sources.save,raw,identity)}


@api.post('/profile-sources/{identity}/refresh')
def refresh_profile_source(identity: str,raw: dict):
    from modules.agents import profile_sources as sources
    return {'item':checked(sources.refresh,identity,raw.get('version'))}


@api.post('/profile-sources/{identity}/remove')
def remove_profile_source(identity: str,raw: dict):
    from modules.agents import profile_sources as sources
    return checked(sources.remove,identity,raw.get('version'))


@api.post('/specialist-update-preview')
def specialist_update_preview(raw: dict,user=Depends(owner_auth)):
    import difflib
    from modules.agents import specialists
    from modules.agents.projection import visible
    agent=checked(service.store().get,raw.get('agent_id'))
    if not visible(agent,user):
        raise HTTPException(404,'Agent unavailable.')
    saved=agent.get('specialist_profile')
    if not saved:
        raise HTTPException(422,'This agent has no specialist profile.')
    current=checked(specialists.detail,saved['id'])
    return {'profile':current,'diff':'\n'.join(difflib.unified_diff(saved['content'].splitlines(),current['content'].splitlines(),fromfile='Saved instructions',tofile='Available instructions',lineterm='')) or 'Instructions are unchanged.'}


@api.get('/specialists/{identity}')
def specialist_detail(identity: str):
    from modules.agents import specialists
    return checked(specialists.detail, identity)


@api.post('/specialist-preview')
def specialist_preview(raw: dict, user=Depends(owner_auth)):
    from modules.agents import specialists
    from modules.agents.projection import visible
    existing = checked(service.store().get, raw['agent_id']) if raw.get('agent_id') else None
    if existing and not visible(existing, user):
        raise HTTPException(404, 'Agent unavailable.')
    item = checked(service.validate, raw.get('profile'), existing)
    return {'instructions': specialists.compose(item),
            'status': 'Applied to new Hermes sessions' if item['runtime'] == 'hermes' else 'Provider setup required'}


@api.get('/entities')
def connected_entities(user=Depends(owner_auth)):
    from modules.agents.entities import snapshot
    return snapshot(user)


@api.get('/entity-types')
def entity_types(user=Depends(owner_auth)):
    from modules.agents.entity_catalog import listing
    return checked(listing, user)


@api.post('/entity-types')
def save_entity_type(raw: dict, user=Depends(owner_auth)):
    from modules.agents.entity_catalog import save
    return checked(save, user, raw)


@api.post('/entity-types/remove')
def remove_entity_type(raw: dict, user=Depends(owner_auth)):
    from modules.agents.entity_catalog import remove
    return checked(remove, user, raw.get('id'), raw.get('replacement'))


@api.post('/entity-types/cleanup')
def cleanup_entity_types(user=Depends(owner_auth)):
    from modules.agents.entity_catalog import cleanup
    return checked(cleanup, user)


@api.post('/items/{identity}/grok-outputs')
def grok_outputs(identity: str, user=Depends(owner_auth)):
    from modules.integrations.grokbot_outputs import refresh
    return checked(refresh, user, identity)


@api.post('/entities/associate')
def associate_entity(raw: dict, user=Depends(owner_auth)):
    from modules.agents.entities import associate
    return checked(associate, user, raw.get('agent_id'), raw.get('entity_id'), raw.get('linked'))


@api.post('/entities/merge')
def merge_entities(raw: dict, user=Depends(owner_auth)):
    from modules.agents.entities import merge
    return checked(merge, user, raw.get('source'), raw.get('target'), raw.get('confirmed', False))


@api.post('/entities/unmerge')
def unmerge_entities(raw: dict, user=Depends(owner_auth)):
    from modules.agents.entities import unmerge
    return checked(unmerge, user, raw.get('merge_id'))


@api.post('/connections/test')
def test_connection(raw: dict, user=Depends(owner_auth)):
    from modules.agents import connections
    return checked(connections.test, user, raw)


@api.get('/items/{identity}/connection')
def connection_settings(identity: str, user=Depends(owner_auth)):
    from modules.agents import connections
    return checked(connections.read, user, identity)


@api.get('/items/{identity}/connection/status')
def connection_status(identity: str, user=Depends(owner_auth)):
    from modules.agents import connections
    return checked(connections.status, user, identity)


@api.post('/items/{identity}/connection/test')
def test_agent_connection(identity: str, raw: dict, user=Depends(owner_auth)):
    from modules.agents import connections
    return checked(connections.test, user, raw, identity)


@api.post('/items/{identity}/connection')
def save_connection(identity: str, raw: dict, user=Depends(owner_auth)):
    from modules.agents import connections
    return checked(connections.save, user, identity, raw)


@api.get('/items/{identity}/conversations')
def agent_conversations(identity: str, user=Depends(owner_auth)):
    from modules.agents import assistant, connections
    checked(connections.agent_for, user, identity)
    return {'items': assistant.conversations(user, identity)}


@api.post('/items/{identity}/conversations')
def new_agent_conversation(identity: str, raw: dict, user=Depends(owner_auth)):
    from modules.agents import assistant
    return checked(assistant.create_fleet_conversation, user, identity, raw)


def measured(request, produce):
    from time import perf_counter
    import hashlib, json
    from fastapi.responses import JSONResponse
    start = perf_counter()
    data = produce()
    stable = {k:v for k,v in data.items() if k not in {'generated_at','projection_ms'}}
    etag = '"' + hashlib.sha256(json.dumps(stable,sort_keys=True,default=str).encode()).hexdigest() + '"'
    response = JSONResponse(data)
    response.headers['ETag'] = etag
    response.headers['Cache-Control'] = 'private, no-cache'
    response.headers['Server-Timing'] = 'projection;dur=' + str(round((perf_counter()-start)*1000,1))
    response.headers['X-Projection-Bytes'] = str(len(response.body))
    if request.headers.get('if-none-match') == etag:
        return Response(status_code=304, headers={k:v for k,v in response.headers.items() if k not in {'content-length','content-type'}})
    return response


@api.get('/work')
def work_items(request: Request, offset: int = 0, limit: int = 40, assigned_only: bool = False, agent_id: str = '', user=Depends(owner_auth)):
    from modules.agents.work import listing
    return measured(request, lambda: checked(listing, user, offset, limit, assigned_only, agent_id))


@api.post('/work/focus')
def focus_work(raw: dict, user=Depends(owner_auth)):
    from modules.agents.work import pin
    return checked(pin, user, raw)


@api.get('/graph')
def ecosystem_graph(request: Request, node_limit: int = 1000, user=Depends(owner_auth)):
    from modules.agents.ecosystem import graph
    if not 100 <= node_limit <= 5000:
        raise HTTPException(422, 'Choose a graph limit from 100 to 5000.')
    def bounded():
        data = graph(user)
        total = len(data['nodes'])
        # Preserve the fleet inventory before filling the remaining budget with activity.
        # A large corpus must not crowd workflow definitions out of the API response.
        priority = {'owner': 0, 'agent': 0, 'connector': 0, 'hud': 1, 'workflow': 1,
                    'application': 2, 'configuration': 2, 'trigger': 2, 'subagent': 2, 'skill': 2,
                    'action': 3, 'idea': 3, 'status': 3}
        ranked = sorted(data['nodes'], key=lambda n: (priority.get(n['kind'], 4), n['id']))
        data['nodes'] = ranked[:node_limit]
        ids = {n['id'] for n in data['nodes']}
        data['edges'] = [e for e in data['edges'] if e['source'] in ids and e['target'] in ids]
        data['coverage']['graph'] = {'returned':len(data['nodes']),'total':total,'limit':node_limit,'has_more':total>node_limit}
        for name, source in data['coverage'].items():
            if name != 'graph' and source.get('has_more'):
                data['warnings'].append(name.replace('_',' ').capitalize() + ' shows only the latest ' + str(source['limit']) + ' records; older records may exist.')
        if total>node_limit:data['warnings'].append('Graph shows '+str(node_limit)+' of '+str(total)+' projected nodes. Use Activity Graph for memory retrieval; Agent work is independent.')
        return data
    return measured(request, bounded)


@api.post('/ideas/{identity}/assignment')
def assign_idea(identity: str, raw: dict, user=Depends(owner_auth)):
    from modules.hfl_corpus.ideas_api import canonical_snapshot
    from modules.hfl_corpus.action_agents import store
    from modules.agents.projection import listing
    if not any(i['id'] == identity for i in canonical_snapshot(include_promoted=True).get('ideas', [])):
        raise HTTPException(404, 'Idea unavailable or protected.')
    agent_id = raw.get('agent_id', '')
    if not isinstance(agent_id, str) or (agent_id and not any(a['id'] == agent_id and a['active'] for a in listing(user))):
        raise HTTPException(422, 'Choose an active fleet agent.')
    if agent_id:
        from modules.agents.availability import require
        require(user, service.store().get(agent_id))
    import json
    with store().connect() as db:
        db.execute('BEGIN IMMEDIATE')
        row = db.execute('SELECT value FROM action_agent_configs WHERE key=?', ('idea:' + identity,)).fetchone()
        current = json.loads(row['value']).get('agent_id', '') if row else ''
        if raw.get('previous_agent_id', '') != current:
            raise HTTPException(409, 'Assignment changed. Refresh and try again.')
        db.execute('INSERT INTO action_agent_configs VALUES (?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value',
                   ('idea:' + identity, json.dumps({'agent_id': agent_id})))
    return {'agent_id': agent_id}


@api.get('/entries/{identity}/description')
def entry_description(identity: str):
    from modules.hfl_corpus.fleet_entry_cache import current_entries
    from modules.agents.corpus_projection import description_html
    entry = next((entry for entry in current_entries() if entry['id'] == identity), None)
    if entry is None:
        raise HTTPException(404, 'Entry unavailable or protected.')
    return {'html': description_html(entry.get('text', ''))}


@api.post('/observations')
def ecosystem_observation(raw: dict, user=Depends(owner_auth)):
    from modules.agents.ecosystem import record
    return checked(record, user, raw)


@api.post('/demo')
def ecosystem_demo(user=Depends(owner_auth)):
    from modules.agents.ecosystem import seed_demo
    return seed_demo(user)


@api.get('/butler')
def butler_history(user=Depends(owner_auth)):
    from modules.agents.butler import history
    return {'messages': history(user)}


@api.get('/assistant')
def assistant_status(probe: bool = True, user=Depends(owner_auth)):
    from modules.agents import assistant
    return checked(assistant.status, user, probe)


@api.post('/assistant/primary')
def assistant_primary(raw: dict, user=Depends(owner_auth)):
    from modules.agents import assistant
    return checked(assistant.select, user, raw)


@api.get('/assistant/conversations')
def assistant_conversations(user=Depends(owner_auth)):
    from modules.agents import assistant
    return {'items': assistant.conversations(user)}


@api.post('/assistant/conversations')
def assistant_new(raw: dict, user=Depends(owner_auth)):
    from modules.agents import assistant
    return checked(assistant.create_conversation, user, raw)


@api.get('/assistant/conversations/{identity}')
def assistant_messages(identity: str, user=Depends(owner_auth)):
    from modules.agents import assistant
    return checked(assistant.refresh, user, identity)


@api.post('/assistant/conversations/{identity}/messages')
def assistant_send(identity: str, raw: dict, user=Depends(owner_auth)):
    from modules.agents import assistant
    return checked(assistant.send, user, identity, raw)


@api.get('/assistant/conversations/{identity}/turns/{turn}/events')
def assistant_events(identity: str, turn: str, user=Depends(owner_auth)):
    from modules.agents import assistant
    return StreamingResponse(checked(assistant.events, user, identity, turn), media_type='text/event-stream',
                             headers={'Cache-Control': 'no-store', 'X-Accel-Buffering': 'no'})


@api.post('/assistant/conversations/{identity}/turns/{turn}/{operation}')
def assistant_control(identity: str, turn: str, operation: str, raw: dict, user=Depends(owner_auth)):
    from modules.agents import assistant
    return checked(assistant.control, user, identity, turn, operation, raw)


@api.get('/assistant/conversations/{identity}/proposals')
def assistant_proposals(identity: str, user=Depends(owner_auth)):
    from modules.agents import assistant
    return {'items': assistant.proposals(user, identity)}


@api.post('/assistant/conversations/{identity}/proposals')
def assistant_proposal(identity: str, raw: dict, user=Depends(owner_auth)):
    from modules.agents import assistant
    return checked(assistant.proposal, user, identity, raw)


@api.post('/assistant/proposals/{identity}')
def assistant_decide(identity: str, raw: dict, user=Depends(owner_auth)):
    from modules.agents import assistant
    return checked(assistant.decide, user, identity, raw)


@api.get('/butler/read-receipts')
def briefing_read_receipts(user=Depends(owner_auth)):
    from modules.agents.read_receipts import read
    return checked(read, user)


@api.post('/butler/read-receipts')
def save_briefing_read_receipts(raw: dict, user=Depends(owner_auth)):
    from modules.agents.read_receipts import save
    return checked(save, user, raw)


@api.get('/butler/briefings')
def delivered_briefings(user=Depends(owner_auth)):
    from modules.agents.briefings import history
    return checked(history, user)


@api.post('/butler/briefings/demo')
def sample_briefings(user=Depends(owner_auth)):
    from modules.agents.briefings import seed_demo
    return checked(seed_demo, user)


@api.get('/butler/schedule')
def briefing_schedule(user=Depends(owner_auth)):
    from modules.agents.briefings import read
    return read(user)


@api.post('/butler/schedule')
def save_briefing_schedule(raw: dict, user=Depends(owner_auth)):
    from modules.agents.briefings import save
    return checked(save, user, raw)


@api.post('/butler')
def butler_message(raw: dict, user=Depends(owner_auth)):
    from modules.agents.butler import send
    return checked(send, user, raw)


@api.get('/defaults')
def defaults():
    return service.read_settings()


@api.post('/defaults')
def save_defaults(raw: dict):
    from modules.app_settings.store import save_settings, DEFAULTS
    if set(raw) - set(DEFAULTS):
        raise HTTPException(422, 'Unsupported execution defaults.')
    return checked(save_settings, raw)


@api.get('/items')
def items(user=Depends(owner_auth)):
    from modules.agents.projection import listing
    return {'items': listing(user)}


@api.post('/items')
def create(raw: dict, user=Depends(owner_auth)):
    from modules.agents.availability import require
    item = checked(service.validate, raw)
    require(user, {**item, 'active': True})
    return {'item': checked(service.initialize().save, item)}


@api.post('/items/{identity}')
def update(identity: str, raw: dict, user=Depends(owner_auth)):
    db = service.initialize()
    item = checked(db.get, identity)
    from modules.agents.projection import visible
    if item.get('mock') and not visible(item, user):
        raise HTTPException(404, 'Agent unavailable.')
    if item.get('connector_user') and item['connector_user'] != user:
        raise HTTPException(404, 'Agent unavailable.')
    return {'item': checked(db.save, checked(service.validate, raw, item), identity=identity, version=raw.get('version'))}


@api.post('/items/{identity}/prepare')
def prepare(identity: str, user=Depends(owner_auth)):
    return checked(service.prepare, identity, user)


@api.get('/items/{identity}/activity')
def activity(identity: str, user=Depends(owner_auth)):
    from modules.agents.projection import inspectable
    agent = checked(service.store().get, identity)
    if not inspectable(agent, user):
        raise HTTPException(404, 'Agent unavailable.')
    from modules.hfl_corpus.action_agents import store as terminals
    db = terminals()
    sessions = [s for s in db.sessions() if s['settings'].get('fleet_agent', {}).get('id') == identity]
    runs = [r for r in db.list(limit=1000) if r['snapshot'].get('execution_settings', {}).get('fleet_agent', {}).get('id') == identity]
    return {'events': service.store().events(identity),
            'sessions': [{k: s[k] for k in ('id', 'source_id', 'state', 'title', 'created', 'activity')} for s in sessions[:50]],
            'runs': [{k: r[k] for k in ('id', 'state', 'source_key', 'updated_at')} for r in runs[:50]]}


@api.post('/assets')
async def upload(request: Request):
    form = await request.form(max_files=1, max_fields=0)
    file = form.get('file')
    if not hasattr(file, 'read'):
        raise HTTPException(422, 'Choose one PNG, GIF or Markdown file.')
    content = await file.read(2 * 1024 * 1024 + 1)
    if len(content) > 2 * 1024 * 1024:
        raise HTTPException(413, 'Use a file smaller than 2 MB.')
    name = (file.filename or '').replace('\\', '/').rsplit('/', 1)[-1][:120]
    if name.lower().endswith('.md'):
        try:
            text = content.decode('utf-8')
            if not text.strip() or len(text) > 50000 or '\x00' in text:
                raise ValueError()
        except (ValueError, UnicodeError):
            raise HTTPException(422, 'Use UTF-8 Markdown, up to 50,000 characters.') from None
        media = 'text/markdown'
    else:
        try:
            with Image.open(io.BytesIO(content)) as picture:
                if picture.format not in {'PNG', 'GIF'} or max(picture.size) > 2048 or getattr(picture, 'n_frames', 1) > 200:
                    raise ValueError()
                media = 'image/' + picture.format.lower()
                picture.verify()
        except Exception:
            raise HTTPException(422, 'Use a valid PNG or GIF up to 2048 pixels and 200 frames.') from None
    identity = service.store().put_asset(name, media, content)
    return {'id': identity, 'name': name, 'media_type': media}


@api.get('/assets/{identity}')
def asset(identity: str):
    value = checked(service.store().asset, identity)
    return Response(value['content'], media_type=value['media_type'],
                    headers={'X-Content-Type-Options': 'nosniff', 'Cache-Control': 'private, max-age=3600',
                             'Content-Disposition': 'inline' if value['media_type'].startswith('image/') else 'attachment'})


@api.post('/audit/deliver')
def deliver():
    from modules.agents.audit import deliver_pending
    return deliver_pending()


router.include_router(api)
