"""Owner session/bearer commands shared by the directory and external agents."""
import json
from uuid import UUID

from fastapi import APIRouter, BackgroundTasks, HTTPException, Request
from itsdangerous import BadSignature, URLSafeTimedSerializer
from pydantic import BaseModel, ConfigDict, Field
from starlette.concurrency import run_in_threadpool

from config import get_settings
from modules.hfl_corpus import entities
from workflows.hfl import entity_merges as merges
from workflows.hfl.entity_store import digest, get_store

router = APIRouter(prefix='/api/hfl/entities')


class MergePreview(BaseModel):
    model_config = ConfigDict(extra='forbid')
    entity_ids: list[str] = Field(min_length=2, max_length=10000)
    name: str = Field(min_length=1, max_length=120)
    evidence: str = Field(default='', max_length=10000)


class MergeSubmit(MergePreview):
    request_id: UUID
    preview_token: str


class Unmerge(BaseModel):
    model_config = ConfigDict(extra='forbid')
    request_id: UUID
    evidence: str = Field(default='', max_length=10000)


def owner(request):
    from modules.hfl_corpus.entities_api import authorize
    return authorize(request)


def signer():
    return URLSafeTimedSerializer(get_settings().secret_key, salt='entity-merge-preview')


def unique(values):
    # Exact values retain case-sensitive URL paths and identifiers.
    return list(dict.fromkeys(v.strip() for v in values if v and v.strip()))


def build_preview(payload):
    ids = list(dict.fromkeys(payload.entity_ids))
    name = payload.name.strip()
    if len(ids) < 2 or not name or entities.is_link(name):
        raise ValueError('Select at least two distinct entities and enter a name, not a URL')
    store = get_store()
    with store.connection() as db:
        version = merges.revision(db)
    available = {e['id']: e for e in entities.entity_index()}
    if any(identity not in available for identity in ids):
        raise ValueError('A selected entity is unavailable or has changed; refresh the directory')
    selected = [available[identity] for identity in ids]
    kinds = {e['kind'] for e in selected}
    if len(kinds) != 1:
        raise ValueError('All selected entities must have the same type')
    profile = {'name': name}
    for key in ('categories', 'emails', 'phones', 'references'):
        profile[key] = unique(v for e in selected for v in (e.get('profile') or {}).get(key, []))
    profile['notes'] = '\n\n'.join(f"### {e['label']}\n{e['profile']['notes']}" for e in selected
                                  if (e.get('profile') or {}).get('notes'))
    with store.connection() as db:
        if merges.revision(db) != version:
            raise ValueError('Entities changed during preview; try again')
    members = [dict(id=e['id'], label=e['label'], profile=e.get('profile')) for e in selected]
    return dict(name=name, kind=selected[0]['kind'], members=members, profile=profile,
                evidence=payload.evidence.strip(), revision=version,
                unique_entries=len({x['id'] for e in selected for x in e['entries']}))


async def call(function, *args):
    try:
        return await run_in_threadpool(function, *args)
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc


@router.post('/merge-preview')
async def preview(request: Request, payload: MergePreview):
    owner(request)
    result = await call(build_preview, payload)
    result['preview_token'] = signer().dumps(digest(result))
    return result


@router.post('/merges')
async def submit(request: Request, payload: MergeSubmit, background_tasks: BackgroundTasks):
    actor = owner(request)
    fingerprint = digest({'action': 'merge', **payload.model_dump(exclude={'request_id', 'preview_token'})})
    existing = await call(merges.operation, str(payload.request_id), fingerprint)
    if existing:
        background_tasks.add_task(merges.flush_audits)
        return existing
    try:
        expected = signer().loads(payload.preview_token, max_age=900)
    except BadSignature as exc:
        raise HTTPException(409, 'Preview expired or invalid; review a fresh preview') from exc
    result = await call(build_preview, payload)
    if digest(result) != expected:
        raise HTTPException(409, 'Selection, fields or entity data changed; review a fresh preview')
    result = await call(merges.commit_merge, result, str(payload.request_id), fingerprint, actor)
    background_tasks.add_task(merges.flush_audits)
    return result


@router.post('/merges/{identity}/unmerge')
async def unmerge(request: Request, identity: str, payload: Unmerge, background_tasks: BackgroundTasks):
    actor = owner(request)
    fingerprint = digest({'action': 'unmerge', 'identity': identity, 'evidence': payload.evidence})
    result = await call(merges.unmerge, identity, str(payload.request_id), fingerprint, actor, payload.evidence)
    background_tasks.add_task(merges.flush_audits)
    return result


@router.get('/operations/{request_id}')
async def operation_status(request: Request, request_id: UUID):
    owner(request)
    def read():
        with get_store().connection() as db:
            row = db.execute('SELECT result FROM entity_operations WHERE request_id=?', (str(request_id),)).fetchone()
            if not row:
                raise HTTPException(404, 'No committed operation found; retry with the same request ID and payload')
            result = json.loads(row[0])
            event = db.execute('SELECT delivery,error FROM entity_audit WHERE id=?', (result['event_id'],)).fetchone()
            return {**result, 'audit_delivery': dict(event) if event else None}
    return await run_in_threadpool(read)


@router.get('/audit/{identity}')
async def history(request: Request, identity: str):
    owner(request)
    return {'events': await run_in_threadpool(merges.history, identity)}
