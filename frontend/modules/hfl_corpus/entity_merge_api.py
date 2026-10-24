"""Owner session/bearer commands shared by the directory and external agents."""
import json
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, BackgroundTasks, HTTPException, Query, Request
from itsdangerous import BadSignature, URLSafeTimedSerializer
from pydantic import BaseModel, ConfigDict, Field, ValidationError
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


class MergeFields(BaseModel):
    model_config = ConfigDict(extra='forbid')
    aliases: list[str] = Field(default_factory=list, max_length=10000)
    partial_aliases: list[str] = Field(default_factory=list, max_length=10000)
    preferred_name: bool = False
    categories: list[str] = Field(default_factory=list)
    emails: list[str] = Field(default_factory=list)
    phones: list[str] = Field(default_factory=list)
    references: list[str] = Field(default_factory=list)
    notes: str = ''


class MergeSubmit(MergePreview):
    request_id: UUID
    preview_token: str
    profile: MergeFields | None = None


class Unmerge(BaseModel):
    model_config = ConfigDict(extra='forbid')
    request_id: UUID
    evidence: str = Field(default='', max_length=10000)


class DetachPreview(BaseModel):
    model_config = ConfigDict(extra='forbid')
    member_id: str = Field(min_length=1, max_length=200)


class DetachSubmit(DetachPreview):
    request_id: UUID
    preview_token: str


def owner(request):
    from modules.hfl_corpus.entities_api import authorize
    return authorize(request)


def signer():
    return URLSafeTimedSerializer(get_settings().secret_key, salt='entity-merge-preview')


def unique(values):
    # Exact values retain case-sensitive URL paths and identifiers.
    return list(dict.fromkeys(v.strip() for v in values if v and v.strip()))


def build_preview(payload, current=None):
    ids = list(dict.fromkeys(payload.entity_ids))
    name = payload.name.strip()
    if len(ids) < 2 or not name or entities.is_link(name):
        raise ValueError('Select at least two distinct entities and enter a name, not a URL')
    store = get_store()
    with store.connection() as db:
        version = merges.revision(db)
    available = {e['id']: e for e in (entities.entity_index() if current is None else current)}
    if any(identity not in available for identity in ids):
        raise ValueError('A selected entity is unavailable or has changed; refresh the directory')
    selected = [available[identity] for identity in ids]
    kinds = {e['kind'] for e in selected}
    if len(kinds) != 1:
        raise ValueError('All selected entities must have the same type')
    profile = {'name': name}
    for key in ('categories', 'emails', 'phones', 'references', 'aliases', 'partial_aliases'):
        profile[key] = unique(v for e in selected for v in (e.get('profile') or {}).get(key, []))
    profile['aliases'] = unique([*profile['aliases'], *(e['label'] for e in selected if e['label'] != name)])
    profile['alias_sources'] = {v: next(((e.get('profile') or {}).get('alias_sources', {}).get(v, 'user') for e in selected if v in (e.get('profile') or {}).get('aliases', []) or v in (e.get('profile') or {}).get('partial_aliases', [])), 'merged-name') for v in [*profile['aliases'], *profile['partial_aliases']]}
    profile['preferred_name'] = any((e.get('profile') or {}).get('preferred_name') and e['label'] == name for e in selected)
    profile['notes'] = '\n\n'.join(f"### {e['label']}\n{e['profile']['notes']}" for e in selected
                                  if (e.get('profile') or {}).get('notes'))
    from modules.hfl_corpus.entities_api import Profile, validated_profile
    profile.update(validated_profile(Profile(**profile)))
    with store.connection() as db:
        if merges.revision(db) != version:
            raise ValueError('Entities changed during preview; try again')
    members = [dict(id=e['id'], label=e['label'], profile=e.get('profile')) for e in selected]
    return dict(name=name, kind=selected[0]['kind'], members=members, profile=profile,
                selection_hash=digest(selected),
                evidence=payload.evidence.strip(), revision=version,
                unique_entries=len({x['id'] for e in selected for x in e['entries']}))


async def call(function, *args):
    try:
        return await run_in_threadpool(function, *args)
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc


def preview_digest(result):
    # Unrelated enrichment and merges must not invalidate a reviewed selection.
    return digest({k: v for k, v in result.items() if k != 'revision'})


@router.post('/merge-preview')
async def preview(request: Request, payload: MergePreview):
    owner(request)
    result = await call(build_preview, payload)
    result['preview_token'] = signer().dumps(preview_digest(result))
    return result


@router.post('/merges')
async def submit(request: Request, payload: MergeSubmit, background_tasks: BackgroundTasks):
    actor = owner(request)
    fingerprint = digest({'action': 'merge', **payload.model_dump(exclude={'request_id', 'preview_token'}, exclude_none=True)})
    existing = await call(merges.operation, str(payload.request_id), fingerprint)
    if existing:
        background_tasks.add_task(merges.flush_audits)
        return existing
    try:
        expected = signer().loads(payload.preview_token, max_age=900)
    except BadSignature as exc:
        raise HTTPException(409, 'Preview expired or invalid; review a fresh preview') from exc
    result = await call(build_preview, payload)
    if preview_digest(result) != expected:
        raise HTTPException(409, 'Selection, fields or entity data changed; review a fresh preview')
    if payload.profile is not None:
        from modules.hfl_corpus.entities_api import Profile, validated_profile
        sources = result['profile'].get('alias_sources', {})
        try:
            result['profile'] = validated_profile(Profile(**{
                **result['profile'], **payload.profile.model_dump(exclude_unset=True),
            }))
        except (ValidationError, ValueError) as exc:
            raise HTTPException(422, 'Merged profile is invalid; review its fields: ' + str(exc)) from exc
        result['profile']['alias_sources'] = {v: sources.get(v, 'user') for k in ('aliases', 'partial_aliases') for v in result['profile'][k]}
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


def detach_members(identity):
    from workflows.hfl import entity_detach
    store = get_store()
    with store.connection() as db:
        snapshot = entity_detach.tree(db, identity)
        links = {}
        for row in db.execute('SELECT entity_id,entry_id FROM entity_activity_links'):
            links.setdefault(row['entry_id'], []).append(row['entity_id'])
    rows = entity_detach.member_rows(snapshot, entities.current_entries(), store.records(), links)
    with store.connection() as db:
        if digest(entity_detach.tree(db, identity)) != digest(snapshot):
            raise ValueError('Members changed while loading; refresh the dialog')
    return snapshot, rows


@router.get('/merges/{identity}/members')
async def merge_members(request: Request, identity: str):
    owner(request)
    _, rows = await call(detach_members, identity)
    return {'members': rows}


@router.post('/merges/{identity}/detach-preview')
async def detach_preview(request: Request, identity: str, payload: DetachPreview):
    owner(request)
    from workflows.hfl import entity_detach
    snapshot, rows = await call(detach_members, identity)
    change = await call(entity_detach.plan, snapshot, identity, payload.member_id)
    member = next(row for row in rows if row['id'] == payload.member_id)
    result = dict(member=member, changes=change['changes'], retired=change['retired'])
    result['preview_token'] = signer().dumps(dict(action='detach', identity=identity,
        member_id=payload.member_id, revision=change['revision']))
    return result


@router.post('/merges/{identity}/detach')
async def detach_submit(request: Request, identity: str, payload: DetachSubmit, background_tasks: BackgroundTasks):
    actor = owner(request)
    from workflows.hfl import entity_detach
    fingerprint = digest(dict(action='detach', identity=identity, member_id=payload.member_id,
                              preview_token=payload.preview_token))
    existing = await call(merges.operation, str(payload.request_id), fingerprint)
    if existing:
        background_tasks.add_task(merges.flush_audits)
        return existing
    try:
        token = signer().loads(payload.preview_token, max_age=900)
    except BadSignature as exc:
        raise HTTPException(409, 'Preview expired or invalid; review a fresh detach preview') from exc
    if not isinstance(token, dict) or any(token.get(k) != v for k, v in dict(
            action='detach', identity=identity, member_id=payload.member_id).items()):
        raise HTTPException(409, 'Preview does not match the selected member')
    result = await call(entity_detach.commit, identity, payload.member_id, token['revision'],
                        str(payload.request_id), fingerprint, actor)
    background_tasks.add_task(merges.flush_audits)
    return result


@router.get('/matching')
async def matching_status(request: Request, all: bool = False):
    owner(request)
    from workflows.hfl.entity_matching import status
    result = await run_in_threadpool(status, None if all else 100)
    if all:
        current = await run_in_threadpool(entities.entity_index)
        ids = {i for s in result['suggestions'] for i in s['data'].get('entity_ids', [])}
        result['entities'] = [e for e in current if e['id'] in ids]
    return result


class BatchSubmit(BaseModel):
    groups: list[MergeSubmit] = Field(min_length=1, max_length=100)


@router.post('/merges/batch')
async def submit_batch(request: Request, payload: BatchSubmit, background_tasks: BackgroundTasks):
    owner(request)
    seen = set()
    for group in payload.groups:
        if seen.intersection(group.entity_ids):
            raise HTTPException(400, 'Combine overlapping selections into one group before submitting.')
        seen.update(group.entity_ids)
    results = []
    for group in payload.groups:
        try:
            result = await submit(request, group, background_tasks)
            results.append({'request_id': str(group.request_id), 'result': result})
        except HTTPException as exc:
            results.append({'request_id': str(group.request_id), 'error': exc.detail})
        except Exception:
            # A retry with the same request ID recovers a commit whose response was lost.
            results.append({'request_id': str(group.request_id), 'error': 'Merge could not complete. Retry this group.'})
    return {'results': results}


@router.post('/matching/scan')
async def matching_scan(request: Request):
    owner(request)
    from workflows.hfl.entity_matching import request_scan
    return await run_in_threadpool(request_scan)


@router.post('/matching/suggestions/{identity}/dismiss')
async def dismiss_match(request: Request, identity: str):
    owner(request)
    from workflows.hfl.entity_matching import dismiss
    await call(dismiss, identity)
    return {'dismissed':identity}


class ConsolidationFact(BaseModel):
    model_config = ConfigDict(extra='forbid')
    left_entry_id: str | None = Field(default=None, max_length=500)
    right_entry_id: str | None = Field(default=None, max_length=500)
    left_quote: str = Field(max_length=2000)
    right_quote: str = Field(max_length=2000)
    explanation: str = Field(min_length=1, max_length=2000)


class ConsolidationDecision(BaseModel):
    model_config = ConfigDict(extra='forbid')
    decision: Literal['merge', 'review', 'separate']
    reason: str = Field(min_length=1, max_length=10000)
    contradictions: list[str] = Field(default_factory=list, max_length=20)
    facts: list[ConsolidationFact] = Field(default_factory=list, max_length=8)
    aliases: list[str] = Field(default_factory=list, max_length=30)
    partial_aliases: list[str] = Field(default_factory=list, max_length=30)
    reason_code: Literal['insufficient-evidence', 'conflicting-identity', 'different-identities'] | None = None


class IntegrityReview(BaseModel):
    required: bool
    reason: str = Field(min_length=1, max_length=10000)
    operation_ids: list[str] = Field(default_factory=list, max_length=50)


class SeparationReversal(BaseModel):
    left_id: str = Field(min_length=1, max_length=500)
    right_id: str = Field(min_length=1, max_length=500)
    reason: str = Field(min_length=1, max_length=10000)


@router.post('/separations/reverse')
async def separation_reverse(request: Request, payload: SeparationReversal):
    actor = owner(request)
    from workflows.hfl.entity_integrity import reverse_separation
    return await call(reverse_separation, payload.left_id, payload.right_id, payload.reason, actor)


@router.post('/integrity/{identity}')
async def integrity_review(request: Request, identity: str, payload: IntegrityReview):
    actor = owner(request)
    from workflows.hfl.entity_integrity import set_review
    return await call(set_review, identity, payload.required, payload.reason, payload.operation_ids, actor)


@router.get('/resolution')
async def resolution_health(request: Request):
    owner(request)
    from workflows.hfl.entity_resolution import status
    return await call(status)


@router.post('/resolution/{entry_id}/retry')
async def resolution_retry(request: Request, entry_id: str):
    owner(request)
    from workflows.hfl.entity_resolution import retry_failed
    return await call(retry_failed, entry_id)


class ExecutionStart(BaseModel):
    execution_id: str = Field(min_length=1, max_length=100, pattern=r'^[a-zA-Z0-9_-]+$')
    max_pairs: int = Field(default=40, ge=1, le=200)
    seconds: int = Field(default=900, ge=30, le=3600)


class ExecutionClose(BaseModel):
    reason: Literal['budget', 'exhausted', 'provider-failure', 'integrity-concern']
    errors: list[str] = Field(default_factory=list, max_length=20)


@router.post('/consolidation/{run_id}/executions')
async def execution_start(request: Request, run_id: str, payload: ExecutionStart):
    owner(request)
    from workflows.hfl.entity_executions import start
    return await call(start, run_id, payload.execution_id, payload.max_pairs, payload.seconds)


@router.post('/consolidation/{run_id}/executions/{execution_id}/close')
async def execution_close(request: Request, run_id: str, execution_id: str, payload: ExecutionClose):
    owner(request)
    from workflows.hfl.entity_executions import close
    from workflows.hfl.entity_consolidation import dispatch_reports
    result = await call(close, run_id, execution_id, payload.reason, payload.errors)
    await call(dispatch_reports, result['report_id'])
    return result


class ConsolidationBatch(BaseModel):
    decisions: dict[str, ConsolidationDecision] = Field(min_length=1, max_length=20)
    claim_token: str | None = Field(default=None, max_length=100)


class ConsolidationGroup(BaseModel):
    model_config = ConfigDict(extra='forbid')
    anchor_id: str = Field(min_length=1, max_length=500)
    decisions: dict[str, ConsolidationDecision] = Field(min_length=2, max_length=20)
    # Required: the assessor must explicitly check for cross-member conflicts.
    contradictions: list[str] = Field(max_length=20)
    claim_token: str | None = Field(default=None, max_length=100)


@router.post('/consolidation/{run_id}/groups')
async def consolidation_group(request: Request, run_id: str, payload: ConsolidationGroup):
    owner(request)
    from workflows.hfl.entity_consolidation import merge_group
    return await call(merge_group, run_id, payload.model_dump(exclude={'claim_token'}, exclude_none=True), payload.claim_token)


class ConsolidationClaim(BaseModel):
    model_config = ConfigDict(extra='forbid')
    worker_id: str = Field(min_length=1, max_length=100)
    max_pairs: int = Field(default=8, ge=1, le=20)
    max_bytes: int = Field(default=100000, ge=4096, le=1000000)
    lease_seconds: int = Field(default=900, ge=60, le=3600)


class ConsolidationClaimUpdate(BaseModel):
    model_config = ConfigDict(extra='forbid')
    action: Literal['renew', 'release']
    lease_seconds: int = Field(default=900, ge=60, le=3600)


class ConsolidationEvidence(BaseModel):
    model_config = ConfigDict(extra='forbid')
    entity_id: str = Field(min_length=1, max_length=500)
    entry_ids: list[str] = Field(min_length=1, max_length=4)
    claim_token: str | None = Field(default=None, max_length=100)


@router.post('/consolidation/{run_id}/evidence')
async def consolidation_evidence(request: Request, run_id: str, payload: ConsolidationEvidence):
    owner(request)
    from workflows.hfl.entity_consolidation_work import expand_evidence
    return await call(expand_evidence, run_id, payload.entity_id, payload.entry_ids, payload.claim_token)


@router.post('/consolidation/{run_id}/claims')
async def consolidation_claim(request: Request, run_id: str, payload: ConsolidationClaim):
    owner(request)
    from workflows.hfl.entity_consolidation_work import claim_work
    return await call(claim_work, run_id, payload.model_dump())


@router.post('/consolidation/{run_id}/claims/{token}')
async def consolidation_claim_update(request: Request, run_id: str, token: str, payload: ConsolidationClaimUpdate):
    owner(request)
    from workflows.hfl.entity_consolidation_work import update_claim
    return await call(update_claim, run_id, token, payload.action, payload.lease_seconds)


@router.post('/consolidation/{run_id}/checkpoint')
async def consolidation_checkpoint(request: Request, run_id: str):
    owner(request)
    from workflows.hfl.entity_consolidation_work import checkpoint
    return await call(checkpoint, run_id)


@router.post('/consolidation/begin')
async def consolidation_begin(request: Request, compact: bool = False):
    owner(request)
    from workflows.hfl.entity_consolidation import begin, compact_view
    result = await call(begin)
    return compact_view(result) if compact else result


@router.get('/consolidation/{run_id}')
async def consolidation_status(request: Request, run_id: str, compact: bool = False,
                               limit: int = Query(20, ge=1, le=20)):
    owner(request)
    from workflows.hfl.entity_consolidation import load, view, compact_view
    result = await call(lambda: view(load(run_id), limit=limit))
    return compact_view(result) if compact else result


@router.post('/consolidation/{run_id}/decisions/{pair_id}')
async def consolidation_decide(request: Request, run_id: str, pair_id: str, payload: ConsolidationDecision):
    owner(request)
    from workflows.hfl.entity_consolidation import decide
    return await call(decide, run_id, pair_id, payload.model_dump(exclude_none=True))


@router.post('/consolidation/{run_id}/decisions')
async def consolidation_batch(request: Request, run_id: str, payload: ConsolidationBatch):
    owner(request)
    from workflows.hfl.entity_consolidation import decide_batch
    return await call(decide_batch, run_id,
                      {key: value.model_dump(exclude_none=True) for key, value in payload.decisions.items()},
                      payload.claim_token)


@router.post('/consolidation/{run_id}/finish')
async def consolidation_finish(request: Request, run_id: str):
    owner(request)
    from workflows.hfl.entity_consolidation import finish, dispatch_reports, load, view
    result = await call(finish, run_id)
    await call(dispatch_reports, run_id)
    return view(await call(load, run_id))
