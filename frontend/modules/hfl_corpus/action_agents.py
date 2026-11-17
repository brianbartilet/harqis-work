"""Authenticated action terminal transport. Workers own processes; browsers only attach."""
import hashlib
import io
import json
from pathlib import Path
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


def effective(source_id, require_active=True, execute=True):
    configs = store().configs()
    card = configs.get('card:' + source_id, {})
    preset = configs.get('preset:' + card.get('preset', ''), {})
    from modules.hfl_corpus.action_assignment import resolve
    defaults = {**read_settings(), **preset.get('overrides', {})}
    return resolve(card, defaults, execute=execute, require_active=require_active)



@owner.get('/configuration/defaults')
def default_configuration(user=Depends(bridge.owner_auth)):
    settings = read_settings()
    from modules.hfl_corpus.action_assignment import agents, resolve
    card = {'preset': '', 'overrides': {}, 'assignment_mode': 'manual', 'specialist_mode': 'inherit'}
    return {'effective': resolve(card, settings, execute=False), 'card': card, 'agents': agents(user), 'defaults': settings, 'presets': {}}


@owner.get('/assignments')
def assignments(user=Depends(bridge.owner_auth)):
    from modules.agents.projection import listing
    visible = {a['id']: {k: a.get(k, '') for k in ('id', 'name', 'runtime', 'classification', 'thumbnail', 'color')}
               for a in listing(user)}
    return {'items': {key[5:]: [visible[value['agent_id']]]
                      for key, value in store().configs().items()
                      if key.startswith('card:') and value.get('agent_id') in visible}}


@owner.post('/configuration/preview')
def preview_configuration(raw: dict, user=Depends(bridge.owner_auth)):
    from modules.hfl_corpus.action_assignment import validate, resolve
    # Draft previews accept profile references, never arbitrary trusted snapshots.
    identity = raw.pop('source_id', '')
    if not isinstance(identity, str) or len(identity)>100:
        raise HTTPException(400, 'Choose an existing Action.')
    old = {}
    if identity:
        bridge.checked(bridge.action_call, 'GET', '/' + identity)
        old = store().configs().get('card:' + identity, {})
    card = {**bridge.checked(validate, raw, old, user), 'overrides': {}}
    settings = bridge.checked(resolve, card, read_settings(), execute=False)
    preview = dict(settings['action_assignment'])
    task, outcome = raw.get('task_prompt', ''), raw.get('expected_outcome', '')
    if not isinstance(task, str) or len(task)>20000 or not isinstance(outcome, str) or len(outcome)>3000:
        raise HTTPException(400, 'Use bounded Action instructions and outcome.')
    preview['instructions'] = '\n\n'.join(filter(None, [preview['instructions'], '# Task\n'+task if task else '', '# Expected outcome\n'+outcome if outcome else '']))
    return preview


@owner.get('/actions/{source_id}/configuration')
def configuration(source_id: str, user=Depends(bridge.owner_auth)):
    from modules.hfl_corpus.action_assignment import agents
    action = bridge.checked(bridge.action_call, 'GET', '/' + source_id)['item']
    configs = store().configs()
    return {'action': {key: action.get(key, '') for key in ('title','status','prompt','expected_outcome','description','notes','completion_note','due_date','version','checklists')},
            'action_html': {key: str(bridge.render_markdown(action.get(key) or '')) for key in ('prompt','expected_outcome','description','notes','completion_note')},
            'effective': effective(source_id, require_active=False, execute=False), 'defaults': read_settings(),
            'card': configs.get('card:' + source_id, {'preset': '', 'overrides': {}}),
            'agents': agents(user),
            'presets': {key[7:]: value for key, value in configs.items() if key.startswith('preset:')}}


@owner.post('/actions/{source_id}/configuration')
def set_configuration(source_id: str, payload: dict, user=Depends(bridge.owner_auth)):
    configuration(source_id, user)
    selected = payload.get('preset', '')
    if not isinstance(selected, str) or (selected and 'preset:' + selected not in store().configs()):
        raise HTTPException(400, 'Choose an existing preset.')
    from modules.hfl_corpus.action_assignment import validate, resolve
    old = store().configs().get('card:' + source_id, {})
    assignment = bridge.checked(validate, payload, old, user)
    card = {**assignment, 'preset': selected, 'overrides': bridge.checked(overrides, payload.get('overrides', {}))}
    bridge.checked(resolve, card, read_settings(), execute=False)
    store().configure('card:' + source_id, card)
    return configuration(source_id, user)



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
    settings = bridge.checked(effective, source_id)
    settings['initial_context'] = {k: action.get(k, '') for k in ('title','status','prompt','expected_outcome','description','notes','completion_note')}
    if settings.get('fleet_agent'):
        settings['initial_context']['agent'] = settings['fleet_agent']
    from modules.hfl_corpus.intent_board_context import context
    settings['initial_context'].update(board_ids=action.get('board_ids', []), available_boards=context())
    previous = bridge.bridge_store().list('actionable:' + source_id, limit=1)
    if previous:
        settings['initial_context']['last_agent_result'] = previous[0]['result'].get('summary', '')
    # Opening a terminal does not execute the Initial prompt a second time.
    session = bridge.checked(store().start_session, source_id, settings, action['title'], payload.get('restore'))
    from modules.agents.audit import terminal_event
    terminal_event(session, 'session-started')
    return session


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


@owner.post('/sessions/{identity}/images')
def terminal_image(identity: str, payload: dict):
    db = store()
    session = bridge.checked(db.session, identity)
    attachments = bridge.checked(bridge.input_manifest, 'actionable', session['source_id'])['attachments']
    attachment = next((item for item in attachments if item['id'] == payload.get('attachment_id')), None)
    if attachment is None:
        raise HTTPException(404, 'Image is not attached to this action.')
    if Path(attachment['filename']).suffix.lower() not in {'.png', '.jpg', '.jpeg', '.webp', '.gif'}:
        raise HTTPException(400, 'Choose a PNG, JPEG, WebP or GIF image.')
    bridge.checked(db.io, identity, 'image', payload.get('key'), json.dumps(attachment))
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
    if payload.get('io_only') is True:
        session = bridge.checked(db.verify, identity, payload.get('token'))
        return {'input': db.read_io(identity, 'in', max(0, int(payload.get('after', 0)))),
                'cols': session['cols'], 'rows': session['rows'],
                'close': bool(session['closed']) or session['state'] in {'closed','expired','failed'}}
    control = bridge.checked(db.heartbeat_session, identity, payload.get('token'), payload.get('state'), str(payload.get('native_id', '')), read_settings()['agent_concurrency'])
    control['input'] = db.read_io(identity, 'in', max(0, int(payload.get('after', 0))))
    control['expiry_minutes'] = read_settings()['agent_session_expiry_minutes']
    session = db.session(identity)
    from modules.agents.audit import terminal_event
    if session['state'] in {'closed', 'expired', 'failed'}:
        terminal_event(session, 'session-' + session['state'], {'state': session['state']})
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
        from modules.agents.audit import terminal_event
        terminal_event(session, 'artifact', {'name': versioned, 'sha256': digest}, key='file:' + digest)
    return {'name': versioned}
