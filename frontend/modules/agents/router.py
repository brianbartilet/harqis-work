"""Authenticated fleet CRUD, assets, sessions and presentation graph."""
import io
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import Response
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
    return templates.TemplateResponse(request, 'modules/agents/index.html', page_context(
        request, user, 'agents', csrf=make_csrf_token(user)))


@api.get('/catalogue')
def catalogue():
    return service.catalogue()


@api.get('/butler')
def butler_history(user=Depends(owner_auth)):
    from modules.agents.butler import history
    return {'messages': history(user)}


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
def create(raw: dict):
    return {'item': checked(service.initialize().save, checked(service.validate, raw))}


@api.post('/items/{identity}')
def update(identity: str, raw: dict, user=Depends(owner_auth)):
    db = service.initialize()
    item = checked(db.get, identity)
    if item.get('connector_user') and item['connector_user'] != user:
        raise HTTPException(404, 'Agent unavailable.')
    return {'item': checked(db.save, checked(service.validate, raw, item), identity=identity, version=raw.get('version'))}


@api.post('/items/{identity}/prepare')
def prepare(identity: str, user=Depends(owner_auth)):
    return checked(service.prepare, identity, user)


@api.get('/items/{identity}/activity')
def activity(identity: str, user=Depends(owner_auth)):
    from modules.agents.projection import visible
    agent = checked(service.store().get, identity)
    if not visible(agent, user):
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
