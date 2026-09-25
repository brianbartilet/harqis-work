"""Authenticated action terminal transport. Workers own processes; browsers only attach."""
import hashlib
import io
import re

from fastapi import APIRouter, Depends, HTTPException, Request, UploadFile
from fastapi.responses import Response

from modules.app_settings.store import read_settings, validate_settings
from modules.hfl_corpus import agent_bridge as bridge
from workflows.hfl.action_agent_store import ActionAgentStore

owner = APIRouter(prefix='/hfl-corpus/agent-bridge', dependencies=[Depends(bridge.owner_auth)])
worker = APIRouter(prefix='/api/hfl-agent', dependencies=[Depends(bridge.worker_auth)])
CONFIG_KEYS = {'agent_mode','hermes_profile','agent_toolsets','agent_model','agent_provider',
               'agent_default_recipient','agent_timeout_seconds','agent_max_turns',
               'agent_repository','agent_base_branch','agent_host'}


def store():
    return ActionAgentStore(bridge.bridge_store().path)


def overrides(value):
    if not isinstance(value, dict) or set(value) - CONFIG_KEYS:
        raise ValueError('Choose supported agent settings.')
    clean = validate_settings(value)
    return {key: clean[key] for key in value}


def effective(source_id):
    configs = store().configs()
    card = configs.get('card:' + source_id, {})
    preset = configs.get('preset:' + card.get('preset', ''), {})
    return {**read_settings(), **preset.get('overrides', {}), **card.get('overrides', {})}


@owner.get('/actions/{source_id}/configuration')
def configuration(source_id: str):
    bridge.checked(bridge.action_call, 'GET', '/' + source_id)
    configs = store().configs()
    return {'effective': effective(source_id), 'defaults': read_settings(),
            'card': configs.get('card:' + source_id, {'preset': '', 'overrides': {}}),
            'presets': {key[7:]: value for key, value in configs.items() if key.startswith('preset:')}}


@owner.post('/actions/{source_id}/configuration')
def set_configuration(source_id: str, payload: dict):
    configuration(source_id)
    selected = payload.get('preset', '')
    if not isinstance(selected, str) or (selected and 'preset:' + selected not in store().configs()):
        raise HTTPException(400, 'Choose an existing preset.')
    store().configure('card:' + source_id, {'preset': selected, 'overrides': bridge.checked(overrides, payload.get('overrides', {}))})
    return configuration(source_id)


@owner.post('/presets')
def set_preset(payload: dict):
    name = payload.get('name', '')
    if not isinstance(name, str) or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9 _-]{0,63}', name):
        raise HTTPException(400, 'Use a preset name of 1–64 letters, numbers, spaces, underscores or hyphens.')
    store().configure('preset:' + name, {'overrides': bridge.checked(overrides, payload.get('overrides', {}))})
    return {'name': name}


@owner.get('/actions/{source_id}/sessions')
def sessions(source_id: str):
    bridge.checked(bridge.action_call, 'GET', '/' + source_id)
    db = store()
    db.expire_sessions()
    with db.connect() as connection:
        used = db.busy_count(connection)
    return {'sessions': db.sessions(source_id), 'capacity': read_settings()['agent_concurrency'], 'busy': used}


@owner.post('/actions/{source_id}/sessions')
def start_session(source_id: str, payload: dict):
    action = bridge.checked(bridge.action_call, 'GET', '/' + source_id)['item']
    settings = effective(source_id)
    settings['initial_context'] = {k: action.get(k, '') for k in ('title','prompt','expected_outcome','description','notes','completion_note')}
    previous = bridge.bridge_store().list('actionable:' + source_id, limit=1)
    if previous:
        settings['initial_context']['last_agent_result'] = previous[0]['result'].get('summary', '')
    # Opening a terminal does not execute the Initial prompt a second time.
    return bridge.checked(store().start_session, source_id, settings, action['title'], payload.get('restore'))


@owner.get('/sessions/{identity}')
def terminal_view(identity: str, after: int = 0):
    db = store()
    session = bridge.checked(db.session, identity)
    return {'session': session, 'output': db.read_io(identity, 'out', max(0, after))}


@owner.post('/sessions/{identity}')
def terminal_edit(identity: str, payload: dict):
    if set(payload) - {'saved','closed','cols','rows','title'}:
        raise HTTPException(400, 'Invalid session setting.')
    for key in ('saved','closed'):
        if key in payload and type(payload[key]) is not bool:
            raise HTTPException(400, 'Expected a boolean.')
    for key in ('cols','rows'):
        if key in payload and (type(payload[key]) is not int or not 10 <= payload[key] <= 300):
            raise HTTPException(400, 'Terminal dimensions must be 10–300.')
    if 'title' in payload and (not isinstance(payload['title'], str) or len(payload['title']) > 200):
        raise HTTPException(400, 'Invalid session title.')
    bridge.checked(store().edit_session, identity, **payload)
    return {'ok': True}


@owner.post('/sessions/{identity}/input')
def terminal_input(identity: str, payload: dict):
    bridge.checked(store().io, identity, 'in', payload.get('key'), payload.get('data'))
    return {'ok': True}


@owner.get('/sessions/{identity}/transcript')
def transcript(identity: str):
    content = bridge.checked(store().transcript, identity)
    # Strip terminal controls for the portable text artifact; retain raw replay in SQLite.
    content = re.sub(r'\x1b\][^\x07]*(?:\x07|\x1b\\)|\x1b\[[0-?]*[ -/]*[@-~]', '', content)
    return Response(content, media_type='text/plain', headers={'Content-Disposition': f'attachment; filename="session-{identity}.txt"', 'Cache-Control': 'no-store'})


@owner.post('/sessions/{identity}/forget')
def forget_session(identity: str):
    bridge.checked(store().forget, identity)
    return {'ok': True}


@worker.get('/terminals')
def terminal_queue():
    db = store()
    db.expire_sessions()
    return {'sessions': [s for s in db.sessions() if s['state'] == 'queued' and not s['closed']], 'settings': read_settings()}


@worker.post('/terminals/{identity}/claim')
def terminal_claim(identity: str, payload: dict):
    name = payload.get('host', '')
    if not isinstance(name, str) or not re.fullmatch(r'[A-Za-z0-9_.-]{1,200}', name):
        raise HTTPException(400, 'Invalid worker host.')
    pending = bridge.checked(store().session, identity)
    attachments = bridge.checked(bridge.input_manifest, 'actionable', pending['source_id'])['attachments']
    claimed = bridge.checked(store().claim_session, identity, name)
    claimed['attachments'] = attachments
    return claimed


@worker.get('/terminals/{identity}/inputs/{attachment_id}')
def terminal_attachment(identity: str, attachment_id: str, request: Request):
    session = bridge.checked(store().verify, identity, request.headers.get('X-Terminal-Lease'))
    return bridge.input_download('actionable', session['source_id'], attachment_id)


@worker.post('/terminals/{identity}/poll')
def terminal_poll(identity: str, payload: dict):
    db = store()
    control = bridge.checked(db.heartbeat_session, identity, payload.get('token'), payload.get('state'), str(payload.get('native_id', '')), read_settings()['agent_concurrency'])
    control['input'] = db.read_io(identity, 'in', max(0, int(payload.get('after', 0))))
    control['expiry_minutes'] = read_settings()['agent_session_expiry_minutes']
    session = db.session(identity)
    action = bridge.checked(bridge.action_call, 'GET', '/' + session['source_id'])['item']
    control['action_closed'] = action['status'] in {'done','dismissed'}
    return control


@worker.post('/terminals/{identity}/output')
def terminal_output(identity: str, payload: dict):
    db = store()
    bridge.checked(db.verify, identity, payload.get('token'))
    bridge.checked(db.io, identity, 'out', payload.get('key'), payload.get('data'))
    return {'ok': True}


async def attach_output(source_id, name, content):
    if bridge.remote_inputs('actionable'):
        return bridge.input_remote('POST', source_id, files=[('files', (name, content, 'application/octet-stream'))]).json()
    from modules.hfl_corpus.attachments import source_store
    attachments, source = source_store('actionable', source_id)
    return {'attachments': await attachments.upload(source, [UploadFile(filename=name, file=io.BytesIO(content))])}


@worker.post('/terminals/{identity}/files/{name}')
async def terminal_file(identity: str, name: str, request: Request):
    db = store()
    session = bridge.checked(db.verify, identity, request.headers.get('X-Terminal-Lease'))
    if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9._-]{0,119}', name):
        raise HTTPException(400, 'Use a simple filename.')
    content = bytearray()
    async for chunk in request.stream():
        content.extend(chunk)
        if len(content) > 20 * 1024 * 1024:
            raise HTTPException(413, 'Generated files are limited to 20 MB each.')
    digest = hashlib.sha256(content).hexdigest()
    versioned = identity[:8] + '-' + digest[:8] + '-' + name
    with db.connect() as connection:
        exists = connection.execute('SELECT 1 FROM action_agent_files WHERE session=? AND name=? AND digest=?', (identity,name,digest)).fetchone()
    if not exists:
        await attach_output(session['source_id'], versioned, bytes(content))
        with db.connect() as connection:
            connection.execute('INSERT OR IGNORE INTO action_agent_files VALUES (?,?,?)', (identity,name,digest))
    return {'name': versioned}
