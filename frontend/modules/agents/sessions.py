"""Fleet-owned terminals: optional, retry-safe promotion to canonical Actions."""
import hashlib
import json
import socket
import uuid

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from fastapi.responses import FileResponse
from starlette.concurrency import run_in_threadpool
from modules.agents import service
from modules.agents.projection import inspectable
from modules.hfl_corpus import action_agents as terminal
from modules.hfl_corpus.attachments import AttachmentStore

router = APIRouter(prefix='/hfl-corpus/agent-bridge', dependencies=[Depends(terminal.bridge.owner_auth)])


def agent_for(identity, user, active=False):
    agent = terminal.bridge.checked(service.initialize().get, identity)
    if not inspectable(agent, user) or agent.get('mock') or agent.get('managed_sharing') or agent['runtime'] not in {'hermes', 'codex', 'claude'}:
        raise HTTPException(404, 'Fleet CLI agent unavailable.')
    if active and not agent['active']:
        raise HTTPException(409, 'Activate this agent before starting a session.')
    if active:
        from modules.agents.availability import require
        require(user, agent, 'cli')
    return agent


def source(identity, user):
    return 'fleet:' + hashlib.sha256((user + '\0' + identity).encode()).hexdigest()


def owned(identity, user):
    item = terminal.bridge.checked(terminal.store().session, identity)
    if item.get('owner') and item['owner'] != user:
        raise HTTPException(404, 'Session unavailable.')
    if item.get('fleet_id'):
        agent_for(item['fleet_id'], user)
    return item


def files(identity):
    return AttachmentStore(terminal.store().path), 'terminal:' + identity


def restore_files(item):
    if not item.get('fleet_id') or not item.get('restored_from'):
        return
    db, old = files(item['restored_from'])
    target = 'terminal:' + item['id']
    with db.connect() as connection:
        connection.execute('BEGIN IMMEDIATE')
        if not connection.execute('SELECT 1 FROM input_attachments WHERE source=?', (target,)).fetchone():
            db.clone(old, target, [f['id'] for f in db.list(old)], connection)


def manifest(item):
    if item.get('fleet_id'):
        db, key = files(item['id'])
        return db.list(key)
    return terminal.bridge.input_manifest('actionable', item['source_id'])['attachments']


def download(item, attachment_id):
    if not item.get('fleet_id'):
        return terminal.bridge.input_download('actionable', item['source_id'], attachment_id)
    db, key = files(item['id'])
    entry = db.get(key, attachment_id)
    return FileResponse(db.path(entry), filename=entry['name'], media_type='application/octet-stream',
                        headers={'Cache-Control': 'no-store', 'X-Content-Type-Options': 'nosniff'})


@router.get('/fleet/{identity}/configuration')
def configuration(identity: str, user=Depends(terminal.bridge.owner_auth)):
    agent = agent_for(identity, user)
    defaults = terminal.read_settings()
    settings = {**defaults, **agent.get('overrides', {})}
    from modules.agents.availability import for_agent
    health = for_agent(user, agent)
    settings['action_assignment'] = {'name': agent['name'], 'agent_id': identity, 'runtime': agent['runtime'],
                                     'executable': health['cli_available'], 'mode': 'agent',
                                     'reason': health['reason'] or ('' if health['cli_available'] else 'No available CLI runtime.')}
    return {'effective': settings, 'defaults': defaults, 'card': {'agent_id': identity, 'preset': '', 'overrides': {}},
            'presets': {}, 'agent': agent, 'agents': []}


@router.get('/fleet/{identity}/sessions')
def history(identity: str, user=Depends(terminal.bridge.owner_auth)):
    agent_for(identity, user)
    db = terminal.store()
    db.expire_sessions()
    return {'sessions': db.sessions(source(identity, user))}


@router.post('/fleet/{identity}/sessions')
def start(identity: str, payload: dict, user=Depends(terminal.bridge.owner_auth)):
    if set(payload) - {'restore', 'runtime', 'host'} or any(not isinstance(v, str) or len(v) > 200 for v in payload.values()):
        raise HTTPException(422, 'Choose a valid session and runtime.')
    agent = agent_for(identity, user, active=True)
    runtime = agent['runtime']
    if payload.get('runtime') and payload['runtime'] != runtime:
        raise HTTPException(409, 'Start another provider from its own Fleet agent.')
    settings = service.execution(identity) if runtime == 'hermes' else {**terminal.read_settings(), **agent.get('overrides', {})}
    if runtime != 'hermes':
        frozen = {k: agent.get(k) for k in ('id', 'name', 'runtime', 'version', 'persona', 'instructions', 'workspace_ids', 'tools', 'workflows', 'triggers', 'subagents')}
        frozen['hash'] = hashlib.sha256(json.dumps(frozen, sort_keys=True).encode()).hexdigest()
        settings['fleet_agent'] = frozen
    hosts = [h['host'] for h in terminal.store().hosts() if any(r['id'] == runtime and r['available'] for r in h['runtimes'])]
    host = settings.get('agent_host')
    if runtime in {'codex', 'claude'}:
        from modules.integrations import store as integrations
        host = integrations.get(user, runtime).get('host') or socket.gethostname()
    if not host:
        host = socket.gethostname() if socket.gethostname() in hosts else hosts[0] if len(hosts) == 1 else None
    previous = owned(payload['restore'], user) if payload.get('restore') else None
    if previous:
        if previous['source_id'] != source(identity, user):
            raise HTTPException(409, 'Restore a session belonging to this Fleet agent.')
        host = previous['worker'] or previous['settings'].get('agent_host')
        if runtime in {'codex', 'claude'} and host != (integrations.get(user, runtime).get('host') or socket.gethostname()):
            raise HTTPException(409, 'The saved session belongs to another connected installation.')
    if host not in hosts:
        raise HTTPException(409, 'No unambiguous available CLI worker for this agent. Check its configured host and CLI installation.')
    settings.update(agent_host=host, terminal_runtime=runtime)
    from modules.hfl_corpus.action_connections import fleet_context
    settings['initial_context'] = {'title': agent['name'] + ' session', 'agent': settings['fleet_agent'],
        'fleet_connections': {**fleet_context(user, identity), 'guidance': 'Reference context only; connections do not grant authorization.'}}
    item = terminal.bridge.checked(terminal.store().start_session, source(identity, user), settings, agent['name'] + ' session',
                                          payload.get('restore'), owner=user, fleet_id=identity)
    restore_files(item)
    from modules.agents.audit import terminal_event
    terminal_event(item, 'session-started')
    return item


@router.get('/sessions/{identity}/files')
def list_files(identity: str, user=Depends(terminal.bridge.owner_auth)):
    return {'attachments': manifest(owned(identity, user))}


@router.post('/sessions/{identity}/files')
async def upload_files(identity: str, uploads: list[UploadFile] = File(..., alias='files'), user=Depends(terminal.bridge.owner_auth)):
    item = owned(identity, user)
    if not item.get('fleet_id'):
        raise HTTPException(409, 'Upload inputs through the Action.')
    db, key = files(identity)
    return {'attachments': await db.upload(key, uploads)}


@router.get('/sessions/{identity}/files/{attachment_id}')
def get_file(identity: str, attachment_id: str, user=Depends(terminal.bridge.owner_auth)):
    return download(owned(identity, user), attachment_id)


@router.post('/sessions/{identity}/save-action')
async def save_action(identity: str, payload: dict, user=Depends(terminal.bridge.owner_auth)):
    item = owned(identity, user)
    if not item.get('fleet_id'):
        raise HTTPException(409, 'This session already belongs to an Action.')
    db, token = terminal.store(), uuid.uuid4().hex
    if not db.lock('promote:' + identity, token, seconds=1800):
        raise HTTPException(409, 'Session is being saved. Retry shortly.')
    try:
        item = owned(identity, user)
        # Freeze the first submission before contacting the canonical service.
        # A lost response can be retried even if the user edits the form afterward.
        with db.connect() as connection:
            row = connection.execute('SELECT payload FROM terminal_promotions WHERE session=?', (identity,)).fetchone()
            if row:
                draft = json.loads(row['payload'])
            else:
                if item['action_id']:
                    return {'action_id': item['action_id']}
                draft = {}
                for field, limit in [('title', 200), ('expected_outcome', 3000), ('notes', 6000)]:
                    value = payload.get(field, '')
                    if not isinstance(value, str) or len(value) > limit or (field == 'title' and not value.strip()):
                        raise HTTPException(422, 'Enter a title and bounded outcome/notes.')
                    draft[field] = value.strip()
                selected = payload.get('file_ids', [])
                available = {f['id'] for f in manifest(item)}
                if not isinstance(selected, list) or any(not isinstance(f, str) or f not in available for f in selected):
                    raise HTTPException(422, 'Choose files from this session.')
                draft['file_ids'] = list(dict.fromkeys(selected))
                draft['workspace_ids'] = item['settings']['fleet_agent'].get('workspace_ids', [])
                connection.execute('INSERT INTO terminal_promotions VALUES (?,?)', (identity, json.dumps(draft)))
        from modules.integrations.service import canonical
        if draft.get('_action_id'):
            action = (await run_in_threadpool(terminal.bridge.action_call, 'GET', '/' + draft['_action_id']))['item']
        else:
            action = (await run_in_threadpool(canonical, 'POST', '/actions', {k: v for k, v in draft.items() if k != 'file_ids'} |
                               {'request_id': str(uuid.uuid5(uuid.NAMESPACE_URL, 'fleet-promote:' + user + ':' + identity)),
                                'status': 'open', 'agent_enabled': False}))['item']
            draft['_action_id'] = action['id']
            with db.connect() as connection:
                connection.execute('UPDATE terminal_promotions SET payload=? WHERE session=?', (json.dumps(draft), identity))
        if 'card:' + action['id'] not in db.configs():
            db.configure('card:' + action['id'], {'assignment_mode': 'agent', 'agent_id': item['fleet_id'], 'preset': '', 'overrides': {}})
        attachments, key = files(identity)
        for attachment_id in draft['file_ids']:
            entry = attachments.get(key, attachment_id)
            await terminal.attach_output(action['id'], entry['name'], attachments.path(entry).read_bytes())
        with db.connect() as connection:
            connection.execute('UPDATE action_agent_sessions SET action_id=?,title=?,saved=1 WHERE id=?', (action['id'], action['title'], identity))
            connection.execute('DELETE FROM terminal_promotions WHERE session=?', (identity,))
        return {'action_id': action['id']}
    finally:
        db.unlock('promote:' + identity, token)


@router.post('/sessions/{identity}/discard')
def discard(identity: str, user=Depends(terminal.bridge.owner_auth)):
    item = owned(identity, user)
    db, token = terminal.store(), uuid.uuid4().hex
    if not db.lock('promote:' + identity, token, seconds=30):
        raise HTTPException(409, 'Session is being saved. Wait before discarding.')
    try:
        item = owned(identity, user)
        with db.connect() as connection:
            pending = connection.execute('SELECT 1 FROM terminal_promotions WHERE session=?', (identity,)).fetchone()
        if not item.get('fleet_id') or item['action_id'] or pending:
            raise HTTPException(409, 'This session is linked or being saved to an Action. End it or open its Action instead.')
        db.edit_session(identity, closed=True)
        db.expire_sessions()
        item = db.session(identity)
        if item['state'] not in {'closed', 'failed', 'expired'}:
            return {'pending': True}
        attachments, key = files(identity)
        with attachments.connect() as connection:
            connection.execute('DELETE FROM input_attachments WHERE source=?', (key,))
        with db.connect() as connection:
            connection.execute('DELETE FROM action_agent_files WHERE session=?', (identity,))
        db.forget(identity)
        return {'pending': False}
    finally:
        db.unlock('promote:' + identity, token)
