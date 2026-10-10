"""Authenticated role editor and bearer-protected canonical operations."""
import asyncio
import os
from uuid import uuid4
from typing import Literal

from fastapi import APIRouter, HTTPException, Request, UploadFile, File
from pydantic import BaseModel, ConfigDict, Field
from web import require_user, page_context, templates
from modules.hfl_shares.security import make_csrf_token, verify_csrf_token
from modules.roles import store

router = APIRouter(prefix='/roles')
api = APIRouter(prefix='/roles')


class RoleWrite(BaseModel):
    model_config = ConfigDict(extra='forbid')
    revision: int = Field(default=0, ge=0)
    name: str = Field(min_length=1, max_length=100, pattern=r'\S')
    color: str = Field(default='#3b82f6', pattern=r'^#[0-9a-fA-F]{6}$')
    soul: str = Field(default='', max_length=100000)
    workspace_ids: list[str] = Field(default_factory=list, max_length=30)
    entity_ids: list[str] = Field(default_factory=list, max_length=100)
    archived: bool = False


def authorize(request, write=False):
    user, redirect = require_user(request)
    if redirect:
        raise HTTPException(401, 'Sign in to manage roles.')
    if write and not verify_csrf_token(request.headers.get('X-CSRF-Token', ''), user):
        raise HTTPException(403, 'Invalid form token.')
    return user


def catalog():
    from modules.hfl_corpus.workspace_views import listing
    from workflows.hfl.colors import PIN_COLORS
    return {'roles': store.listing(), 'spaces': listing()['views'], 'runs': store.runs(), 'palette': list(PIN_COLORS)}


@router.get('')
async def page(request: Request):
    user, redirect = require_user(request)
    if redirect:
        return redirect
    return templates.TemplateResponse(request, 'modules/roles/index.html', page_context(request, user, 'roles', csrf=make_csrf_token(user)))


@router.get('/data')
async def data(request: Request):
    authorize(request)
    return await asyncio.to_thread(catalog)


@api.get('')
def api_list():
    return catalog()


def persist(payload, identity=None):
    from modules.hfl_corpus.workspace_views import listing
    valid = {v['id'] for v in listing()['views']}
    if not set(payload.workspace_ids).issubset(valid):
        raise HTTPException(422, 'A selected Space is unavailable.')
    if payload.entity_ids:
        from modules.hfl_shares.personalization import entity_catalog
        if not set(payload.entity_ids).issubset({e['id'] for e in entity_catalog()}):
            raise HTTPException(422, 'A selected entity is unavailable.')
    changes = payload.model_dump(exclude={'revision'})
    return store.save(identity, payload.revision, changes)


@router.post('/data')
async def create(request: Request, payload: RoleWrite):
    authorize(request, True)
    return await asyncio.to_thread(persist, payload)


@router.put('/data/{identity}')
async def update(request: Request, identity: str, payload: RoleWrite):
    authorize(request, True)
    return await asyncio.to_thread(persist, payload, identity)


@api.post('')
def api_create(payload: RoleWrite):
    return persist(payload)


@api.put('/{identity}')
def api_update(identity: str, payload: RoleWrite):
    return persist(payload, identity)


@router.get('/data/{identity}/history')
def history(request: Request, identity: str):
    authorize(request)
    return {'history': store.history(identity)}


@router.get('/entities')
def entities(request: Request, q: str = "", kind: str = "people", selected: str = ""):
    authorize(request)
    from modules.hfl_shares.personalization import entity_catalog
    try:
        rows = entity_catalog()
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    rows.sort(key=lambda e: (e['label'].casefold(), e['id']))
    matches = [e for e in rows if (not kind or e['kind'] == kind) and all(word in e['label'].casefold() for word in q.casefold().split())]
    ids = set(selected.split(','))
    return {'entities': matches[:50], 'total': len(matches),
            'types': sorted({e['kind'] for e in rows}),
            'selected': [e for e in rows if e['id'] in ids]}


@router.post('/markdown')
async def markdown(request: Request):
    authorize(request, True)
    from services.markdown import render_markdown
    payload = await request.json()
    return {'html': render_markdown(str(payload.get('text', ''))[:100000])}


@router.post('/data/{identity}/attachments')
async def upload(request: Request, identity: str, files: list[UploadFile] = File(...)):
    authorize(request, True)
    role = store.get(identity)
    from modules.roles.extraction import extract, SUPPORTED, MAX_BYTES
    from pathlib import Path
    if role.get('archived'):
        raise HTTPException(409, 'Restore the role before adding files.')
    if len(files) > 10 or len(role['files']) + len(files) > 20:
        raise HTTPException(422, 'Use at most 20 files per role and 10 per upload.')
    for file in files:
        if Path(file.filename or '').suffix.lower() not in SUPPORTED or (file.size or 0) > MAX_BYTES:
            raise HTTPException(422, 'Use supported files of at most 20 MB each.')
    attachments = store.attachment_store()
    manifests = await attachments.upload('role:' + identity, files)
    records = {f['id']: f for f in role['files']}
    for manifest in manifests:
        if manifest['id'] in records:
            continue
        try:
            result = await asyncio.to_thread(extract, attachments.path(manifest), manifest['name'])
        except Exception:
            result = {'status': 'failed', 'text': '', 'error': 'Extraction failed. Check encryption, format, and OCR availability; detach and upload again.'}
        records[manifest['id']] = {**manifest, **result}
    return store.save(identity, role['revision'], {'files': list(records.values())})


class Revision(BaseModel):
    revision: int = Field(ge=1)


@router.post('/data/{identity}/attachments/{attachment_id}/detach')
def detach(request: Request, identity: str, attachment_id: str, payload: Revision):
    authorize(request, True)
    role = store.get(identity)
    if not any(f['id'] == attachment_id for f in role['files']):
        raise HTTPException(404, 'Attachment not found.')
    result = store.save(identity, payload.revision, {'files': [f for f in role['files'] if f['id'] != attachment_id]})
    store.attachment_store().detach('role:' + identity, attachment_id)
    return result


@router.get('/data/{identity}/attachments/{attachment_id}')
def owner_attachment(request: Request, identity: str, attachment_id: str):
    authorize(request)
    from fastapi.responses import FileResponse
    role = store.get(identity)
    if not any(f['id'] == attachment_id for f in role['files']):
        raise HTTPException(404, 'Attachment not found.')
    attachments = store.attachment_store()
    manifest = attachments.get('role:' + identity, attachment_id)
    return FileResponse(attachments.path(manifest), filename=manifest['name'], media_type='application/octet-stream',
                        headers={'Cache-Control':'no-store', 'X-Content-Type-Options':'nosniff'})


class Review(Revision):
    status: Literal['approved', 'rejected', 'pending']


@router.post('/data/{identity}/journal/{note_id}')
def review(request: Request, identity: str, note_id: str, payload: Review):
    authorize(request, True)
    role = store.get(identity)
    if not any(n['id'] == note_id for n in role['journal']):
        raise HTTPException(404, 'Observation not found.')
    notes = [{**n, 'status': payload.status, 'reviewed_at': store.now()} if n['id'] == note_id else n for n in role['journal']]
    return store.save(identity, payload.revision, {'journal': notes})


@router.post('/analyze')
async def analyze(request: Request):
    authorize(request, True)
    from core.apps.sprout.app.celery import SPROUT
    from workflows.queues import WorkflowQueue
    run_id = uuid4().hex
    store.record_run({'id': run_id, 'status': 'queued', 'created_at': store.now(), 'trigger': 'manual'})
    try:
        result = await asyncio.to_thread(SPROUT.send_task, 'workflows.hfl.tasks.persona_audit.persona_audit',
            kwargs={'run_id': run_id}, queue=os.environ.get('HFL_PERSONA_QUEUE') or WorkflowQueue.HOST)
    except Exception:
        from modules.roles.audit import report
        failed = {'id': run_id, 'status': 'failed', 'error': 'Task could not be queued.', 'created_at': store.now(), 'report_pending': True}
        store.record_run(failed)
        try:
            await asyncio.to_thread(report, failed)
            failed['report_pending'] = False
            store.record_run(failed)
        except Exception:
            pass
        raise HTTPException(503, 'Analysis could not be queued. Try again.') from None
    return {'id': run_id, 'status': 'queued', 'task_id': result.id}


class AuditRequest(BaseModel):
    run_id: str = Field(pattern=r'^[a-zA-Z0-9_-]{1,100}$')


@api.post('/audit/run')
async def run_audit(payload: AuditRequest):
    from modules.roles.audit import run
    return await asyncio.to_thread(run, payload.run_id)
