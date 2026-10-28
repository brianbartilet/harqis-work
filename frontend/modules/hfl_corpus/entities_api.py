"""Owner-only Activity Corpus graph, entity timelines, and enrichment controls."""
from pathlib import Path
import json
import os
from fastapi import APIRouter, HTTPException, Request, Query
from fastapi.responses import RedirectResponse
from pydantic import BaseModel, Field
from starlette.concurrency import run_in_threadpool
from auth import get_current_user
from web import templates, page_context, require_user
from modules.hfl_corpus import entities
from workflows.hfl.entity_store import get_store
from modules.hfl_corpus import graph_views
from modules.hfl_corpus.graph_capacity import DEFAULT_NODES, DEFAULT_EDGES, MIN_NODES, MAX_NODES, MAX_EDGES

router = APIRouter()


@router.get('/api/hfl/graph-views')
async def saved_graph_views(request: Request):
    authorize(request)
    return await run_in_threadpool(graph_views.listing)


@router.post('/api/hfl/graph-views')
async def create_graph_view(request: Request, payload: graph_views.ViewWrite):
    authorize(request)
    return await run_in_threadpool(graph_views.save, payload)


@router.put('/api/hfl/graph-views/{identity}')
async def update_graph_view(request: Request, identity: str, payload: graph_views.ViewWrite):
    authorize(request)
    return await run_in_threadpool(graph_views.save, payload, identity)


@router.post('/api/hfl/graph-views/{identity}/select')
async def select_graph_view(request: Request, identity: str):
    authorize(request)
    await run_in_threadpool(graph_views.select, identity)
    return {'selected': identity}


@router.delete('/api/hfl/graph-views/{identity}')
async def delete_graph_view(request: Request, identity: str, revision: int = Query(ge=1)):
    authorize(request)
    await run_in_threadpool(graph_views.delete, identity, revision)
    return {'deleted': identity}


def authorize(request):
    user = get_current_user(request)
    if user:
        return user
    from fastapi.security import HTTPAuthorizationCredentials
    from modules.hfl_corpus.api import _authorize
    scheme, _, token = request.headers.get('authorization', '').partition(' ')
    if not token:
        raise HTTPException(401, 'Sign in or supply an owner bearer token')
    _authorize(HTTPAuthorizationCredentials(scheme=scheme, credentials=token))
    return 'owner-api'


@router.get('/knowledge')
@router.get('/knowledge/graph')
async def legacy(request: Request):
    return RedirectResponse('/hfl-corpus/graph' + ('?' + request.url.query if request.url.query else ''), 307)


@router.get('/hfl-corpus/actions')
@router.get('/hfl-corpus/graph')
@router.get('/hfl-corpus/ideas')
@router.get('/hfl-corpus/entities')
async def page(request: Request):
    user, redirect = require_user(request)
    if redirect:
        return redirect
    template = 'knowledge_graph.html' if request.url.path.endswith(('/graph', '/ideas')) else 'entities.html'
    if request.url.path.endswith('/actions'):
        template = 'actions_board.html'
    from modules.hfl_shares.security import make_csrf_token
    workspace_context = {}
    if template in ('actions_board.html', 'knowledge_graph.html'):
        from modules.hfl_corpus import workspace_views
        from modules.hfl_corpus.view_scope import parse_scope
        saved = await run_in_threadpool(workspace_views.listing)
        if template == 'knowledge_graph.html' and request.query_params.get('context'):
            from urllib.parse import parse_qsl, urlencode
            params = dict(parse_qsl(request.query_params['context']))
            params.update({k: v for k, v in request.query_params.items() if k != 'context'})
            return RedirectResponse(request.url.path + '?' + urlencode(params), status_code=303)
        graph_navigation = template == 'knowledge_graph.html' and set(request.query_params).issubset({'board', 'map', 'select', 'graph_filters'})
        if (not request.query_params or graph_navigation) and (saved['preferences']['revision'] or saved['last_used']):
            target = workspace_views.selection_url(saved, dynamic=saved['preferences']['dynamic'])
            if graph_navigation and request.query_params:
                from urllib.parse import urlencode
                target += '&' + urlencode(dict(request.query_params))
            return RedirectResponse(target.replace('/hfl-corpus?', request.url.path + '?', 1), status_code=303)
        try:
            values = {key: value for key, value in request.query_params.items() if key in workspace_views.WorkspaceState.model_fields}
            for key in ('rolling', 'page_size'):
                if key in values:
                    values[key] = int(values[key])
            state = workspace_views.WorkspaceState.model_validate(values)
            scope = parse_scope(request.query_params.get('scope'))
        except ValueError:
            raise HTTPException(422, 'Invalid Space filters.') from None
        workspace_context = dict(saved_workspaces=saved, workspace_state=state.model_dump(), workspace_scope=scope.model_dump())
    return templates.TemplateResponse(request, 'modules/hfl_corpus/' + template,
                                      page_context(request, user, 'hfl_corpus', memory_csrf=make_csrf_token(user), **workspace_context))


@router.get('/api/hfl/entities/graph')
async def graph(request: Request, source: str = '', since: str = '', until: str = '',
                limit: int = Query(default=100, ge=0, le=1000),
                query: str = Query(default='', max_length=200), shared: bool = False,
                sources: list[str] = Query(default=[]), context: str = '',
                capacity_guard: bool = False, preview: bool = False,
                node_limit: int = Query(default=DEFAULT_NODES, ge=MIN_NODES, le=MAX_NODES),
                edge_limit: int = Query(default=DEFAULT_EDGES, ge=100, le=MAX_EDGES)):
    authorize(request)
    if capacity_guard:
        from modules.hfl_corpus.graph_capacity import bounded_graph
        return await run_in_threadpool(bounded_graph, sources or source, since, until,
                                      query, shared, context, node_limit, edge_limit, preview)
    return await run_in_threadpool(entities.graph, sources or source, since, until, limit, query, shared, context)


@router.get('/api/hfl/entities')
async def index(request: Request, source: str = '', since: str = '', until: str = '',
                limit: int | None = Query(default=None, ge=0, le=10000),
                q: str = '', kind: str = '', offset: int = Query(default=0, ge=0),
                context: str = '', graph_query: str = '', sources: list[str] = Query(default=[]),
                include_provisional: bool = True):
    authorize(request)
    rows = await run_in_threadpool(entities.entity_index, source, since, until, context, graph_query, sources)
    provisional_total = sum(bool(e.get('provisional')) for e in rows)
    if not include_provisional:
        rows = [e for e in rows if not e.get('provisional')]
    rows.sort(key=lambda e: (e['label'].casefold(), e['id']))
    from workflows.hfl.entity_types import listing
    types = listing()
    counts = {t['id']: sum(e['kind'] == t['id'] for e in rows) for t in types}
    rows = [e for e in rows if (not kind or e['kind'] == kind) and
            all(word in str([e['label'], e.get('categories'), e.get('profile')]).casefold() for word in q.casefold().split())]
    from workflows.hfl.entity_directory_status import annotate
    page = rows[offset:offset + limit] if limit else rows[offset:]
    return {'entities': await run_in_threadpool(annotate, page), 'total': len(rows), 'counts': counts, 'types': types, 'provisional_total': provisional_total}


class Profile(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    aliases: list[str] = Field(default_factory=list, max_length=10000)
    partial_aliases: list[str] = Field(default_factory=list, max_length=10000)
    preferred_name: bool = False
    categories: list[str] = Field(default_factory=list)
    emails: list[str] = Field(default_factory=list)
    phones: list[str] = Field(default_factory=list)
    references: list[str] = Field(default_factory=list)
    notes: str = ''


class TypedProfile(Profile):
    kind: str


class TypeWrite(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    color: str = Field(pattern=r'^#[0-9a-fA-F]{6}$')
    description: str = Field(min_length=1, max_length=1000)


class TopicRemoval(BaseModel):
    request_id: str = Field(min_length=36, max_length=36)
    selection_hash: str = Field(pattern=r'^[0-9a-f]{64}$')


@router.get('/api/hfl/entities/types/topics/removal-preview')
async def topic_removal_preview(request: Request):
    authorize(request)
    from workflows.hfl.entity_retirement import preview
    return await run_in_threadpool(preview)


@router.post('/api/hfl/entities/types/topics/remove')
async def remove_topics(request: Request, payload: TopicRemoval):
    actor = authorize(request)
    from workflows.hfl.entity_retirement import remove_topics
    try:
        return await run_in_threadpool(remove_topics, payload.request_id, payload.selection_hash, actor)
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from None


@router.post('/api/hfl/entities/types')
async def create_type(request: Request, payload: TypeWrite):
    authorize(request)
    from workflows.hfl.entity_types import create
    try:
        return await run_in_threadpool(create, payload.name, payload.color, payload.description)
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc


@router.post('/api/hfl/entities/types/{identity}/update')
async def update_type(request: Request, identity: str, payload: TypeWrite):
    authorize(request)
    from workflows.hfl.entity_types import update
    try:
        return await run_in_threadpool(update, identity, payload.name, payload.color, payload.description)
    except KeyError as exc:
        raise HTTPException(404, 'Entity type not found. Refresh and choose an existing type.') from exc
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc


def validate_kind(kind):
    from workflows.hfl.entity_types import listing
    if kind not in {t['id'] for t in listing()}:
        raise HTTPException(400, 'Choose an existing entity type.')


class CreateProfile(TypedProfile):
    confirm_distinct: bool = False


def creation_suggestions(payload):
    from workflows.hfl.entity_candidates import CandidateIndex, incoming_candidates
    from workflows.hfl.entity_integrity import flagged
    rows = [r for r in entities.entity_index() if r['kind'] == payload.kind
            and not r['id'].startswith('integrity-mention-')]
    probe = dict(id='creation-probe', kind=payload.kind, label=payload.name, profile=payload.model_dump(), entries=[])
    with get_store().connection() as db:
        quarantine = flagged(db)
    return [dict(id=r['id'], name=r['label'], kind=r['kind'], entries=len(r['entries']),
                 integrity_review=r['id'] in quarantine)
            for r in incoming_candidates(probe, CandidateIndex(rows), limit=10)]


@router.post('/api/hfl/entities/possible-existing')
async def possible_existing(request: Request, payload: TypedProfile):
    authorize(request)
    validate_kind(payload.kind)
    return {'suggestions': await run_in_threadpool(creation_suggestions, payload)}


@router.post('/api/hfl/entities/create')
async def create_entity(request: Request, payload: CreateProfile):
    from uuid import uuid4
    actor = authorize(request)
    validate_kind(payload.kind)
    suggestions = await run_in_threadpool(creation_suggestions, payload)
    if suggestions and not payload.confirm_distinct:
        return {'state': 'possible-existing', 'suggestions': suggestions}
    identity = 'manual-' + uuid4().hex
    data = validated_profile(Profile(**payload.model_dump()))
    await run_in_threadpool(get_store().save_profile, identity, payload.kind, data, actor)
    return {'id': identity}


class KindWrite(BaseModel):
    kind: str


class BatchKindWrite(KindWrite):
    entity_ids: list[str] = Field(min_length=1, max_length=10000)
    source_kind: str | None = None
    source_kinds: dict[str, str] = Field(default_factory=dict)


def change_selected_types(payload, actor):
    validate_kind(payload.kind)
    store = get_store()
    available = {e['id']: e for e in entities.entity_index()}
    with store.connection() as db:
        db.execute('BEGIN IMMEDIATE')
        ids = list(dict.fromkeys(payload.entity_ids))
        if any(identity not in available for identity in ids):
            raise HTTPException(404, 'Entity unavailable; refresh the directory.')
        selected = [available[identity] for identity in ids]
        if any(e['kind'] != payload.source_kinds.get(e['id'], payload.source_kind or e['kind']) for e in selected):
            raise HTTPException(409, 'An entity type changed. Refresh the directory.')
        if any(e.get('is_owner') for e in selected) and payload.kind != 'people':
            raise HTTPException(409, 'The corpus owner must remain a People entity.')
        try:
            for entity in selected:
                current = db.execute('SELECT kind,data FROM profiles WHERE id=?', (entity['id'],)).fetchone()
                if current and current['kind'] != entity['kind']:
                    raise HTTPException(409, 'An entity type changed. Refresh the directory.')
                if entity['kind'] == payload.kind:
                    continue
                profile = json.loads(current['data']) if current else entity.get('profile') or {'name': entity['label']}
                data = validated_profile(Profile(**profile))
                store.save_profile(entity['id'], payload.kind, data, actor, connection=db)
        except ValueError as exc:
            raise HTTPException(409, str(exc)) from exc
    return {'kind': payload.kind, 'updated': sum(e['kind'] != payload.kind for e in selected)}


@router.post('/api/hfl/entities/types/batch')
async def change_types(request: Request, payload: BatchKindWrite):
    actor = authorize(request)
    return await run_in_threadpool(change_selected_types, payload, actor)


@router.post('/api/hfl/entities/type/{identity}')
async def change_type(request: Request, identity: str, payload: KindWrite):
    actor = authorize(request)
    validate_kind(payload.kind)
    available = {e['id']: e for e in await run_in_threadpool(entities.entity_index)}
    if identity not in available:
        raise HTTPException(404, 'Entity unavailable; refresh the directory.')
    entity = available[identity]
    if entity.get('is_owner') and payload.kind != 'people':
        raise HTTPException(409, 'The corpus owner must remain a People entity.')
    data = validated_profile(Profile(**(entity.get('profile') or {'name': entity['label']})))
    try:
        await run_in_threadpool(get_store().save_profile, identity, payload.kind, data, actor)
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc
    return {'kind': payload.kind}


def validated_profile(payload: Profile):
    data = payload.model_dump()
    data['name'] = data['name'].strip()
    if not data['name'] or entities.is_link(data['name']):
        raise HTTPException(400, 'Use an entity name, not a link or email address')
    for field in ('categories', 'emails', 'phones', 'aliases', 'partial_aliases'):
        data[field] = list(dict.fromkeys(v.strip() for v in data[field] if v.strip()))
        if any(len(v) > 200 for v in data[field]):
            raise HTTPException(400, 'Contact details and categories must be at most 200 characters each')
    if any(len(v) < 3 for v in data['partial_aliases']):
        raise HTTPException(400, 'Partial aliases need at least three characters')
    import re
    from urllib.parse import urlsplit
    data['references'] = list(dict.fromkeys(v.strip() for v in data['references'] if v.strip()))
    for reference in data['references']:
        try:
            parsed = urlsplit(reference)
            valid = ((parsed.scheme in {'http', 'https'} and bool(parsed.hostname))
                     or (parsed.scheme == 'file' and bool(parsed.path))
                     or reference.startswith(('/', '\\\\'))
                     or bool(re.match(r'^[A-Za-z]:[\\/]', reference)))
        except ValueError:
            valid = False
        if not valid or len(reference) > 2048 or any(ord(c) < 32 for c in reference):
            raise HTTPException(400, 'References must be HTTP(S) links, file:// links or absolute file paths, at most 2048 characters each')
    if any(not re.fullmatch(r'[^\s@]+@[^\s@]+\.[^\s@]+', v) for v in data['emails']):
        raise HTTPException(400, 'Enter valid email addresses, one per line')
    if any(not re.fullmatch(r'[+()0-9 .xX#-]{3,80}', v) or sum(c.isdigit() for c in v) < 3 for v in data['phones']):
        raise HTTPException(400, 'Enter phone numbers, one per line')
    return data


@router.post('/api/hfl/entities/profile/{identity}')
async def save_profile(request: Request, identity: str, payload: Profile):
    actor = authorize(request)
    data = validated_profile(payload)
    available = {e['id']: e for e in await run_in_threadpool(entities.entity_index)}
    if identity not in available:
        raise HTTPException(404, 'Entity unavailable')
    if available[identity].get('is_owner') and data['name'] != available[identity]['label']:
        raise HTTPException(409, 'Update your owner name in /profile.')
    try:
        await run_in_threadpool(get_store().save_profile, identity, available[identity]['kind'], data, actor)
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc
    return {'profile': get_store().profiles()[identity]}


def _entry_document(path):
    """Use the document view's allowlisted reference resolver."""
    from modules.hfl_corpus import router as document_view
    if document_view._uses_remote_corpus():
        profile = document_view.get_profile_store().get()
        document, references = document_view.RemoteCorpusClient.from_settings().document(
            path, include_secrets=False,
            secret_tags=document_view.normalize_secret_tags(profile.secret_tags))
    else:
        document = document_view.corpus_index.get(path)
        if not document:
            raise HTTPException(404, 'Entry unavailable')
        root = document_view.resolve_corpus_root()
        references = [document_view.resolve_reference(
            reference, source_document=document.path or root / document.relative_path,
            corpus_root=root) for reference in document.references]
        references = [document_view._with_reference_preview(r) for r in references]
    return document, [r for r in references if r.kind in {'download', 'external'} and r.href]


def _entry_references(item):
    return _entry_document(item['path'])[1]


@router.get('/api/hfl/entities/entry/{entry_id}')
async def entry_preview(request: Request, entry_id: str, locator: str = ''):
    authorize(request)
    from services.markdown import render_markdown
    from modules.hfl_corpus.corpus import format_hfl_markdown, entry_occurrence_date
    from modules.hfl_corpus.router import _pill_rendered_tags
    from modules.hfl_corpus.remote import RemoteCorpusError
    try:
        if locator:
            from itsdangerous import URLSafeTimedSerializer, BadSignature
            from config import get_settings
            from modules.hfl_corpus.secrets import is_secret_entry, normalize_secret_tags
            from modules.profile.store import get_profile_store
            try:
                location = URLSafeTimedSerializer(get_settings().secret_key, salt='graph-entry-location').loads(locator)
            except BadSignature as exc:
                raise HTTPException(400, 'Invalid entry location') from exc
            if location['id'] != entry_id:
                raise HTTPException(400, 'Entry location mismatch')
            document, references = await run_in_threadpool(_entry_document, location['path'])
            protected = normalize_secret_tags(get_profile_store().get().secret_tags)
            entry = next((e for e in document.entries if e.anchor == location['anchor'] and not is_secret_entry(e, protected)), None)
            if entry is None:
                raise HTTPException(404, 'Entry unavailable')
            import re
            identity = re.search(r'^\s*Entry ID:\s*(\S+)', entry.text, re.M | re.I)
            if identity and identity.group(1) != entry_id:
                raise HTTPException(404, 'Entry unavailable')
            occurred = entry_occurrence_date(entry)
            item = dict(title=entry.moment, text=entry.text, date=occurred.isoformat() if occurred else '', source=entry.source,
                        path=location['path'])
        else:
            rows = await run_in_threadpool(entities.current_entries)
            item = next((e for e in rows if e['id'] == entry_id), None)
            if item is None:
                raise HTTPException(404, 'Entry unavailable')
            references = await run_in_threadpool(_entry_references, item)
    except RemoteCorpusError as exc:
        raise HTTPException(502, 'Entry could not load') from exc
    html = await run_in_threadpool(
        lambda: _pill_rendered_tags(render_markdown(format_hfl_markdown('## '+item['text'], references))))
    from urllib.parse import urlencode
    from modules.hfl_corpus.timeline import entry_evidence_id
    action_url = '/hfl-corpus?' + urlencode({
        'source_path': item['path'], 'source_entry': entry_evidence_id(item['text']),
    })
    return {'title': item['title'], 'date': item['date'], 'source': item['source'],
            'html': str(html), 'action_url': action_url}


@router.get('/hfl-corpus/entities/entry/{entry_id}')
async def entry(request: Request, entry_id: str):
    user, redirect = require_user(request)
    if redirect:
        return redirect
    rows = await run_in_threadpool(entities.current_entries)
    item = next((e for e in rows if e['id'] == entry_id), None)
    if item is None:
        raise HTTPException(404, 'Entry unavailable')
    return templates.TemplateResponse(request, 'modules/hfl_corpus/entity_entry.html',
        page_context(request, user, 'hfl_corpus', entry=item))


@router.get('/api/hfl/entities/status')
async def status(request: Request):
    authorize(request)
    store = get_store()
    from workflows.hfl.entity_resolution import status as resolution_status
    return {'job': store.state('job'), 'enrichment': store.state('enrichment'),
            'decisions': store.decisions(), 'resolution': resolution_status()}


@router.post('/api/hfl/entities/backfill')
async def backfill(request: Request, include_new_types: bool = False):
    authorize(request)
    from workflows.hfl.entity_events import request_enrichment
    if include_new_types:
        from workflows.hfl.entity_types import revision
        get_store().state('entity-types-backfill', revision())
    return await run_in_threadpool(request_enrichment)


class Merge(BaseModel):
    alias: str = Field(max_length=100)
    canonical: str = Field(max_length=100)
    reason: str = Field(min_length=5, max_length=1000)


@router.post('/api/hfl/entities/merge')
async def merge(request: Request, payload: Merge):
    authorize(request)
    available = {e['id']: e for e in await run_in_threadpool(entities.entity_index)}
    if payload.alias not in available or payload.canonical not in available:
        raise HTTPException(400, 'Select two visible entities')
    if available[payload.alias]['kind'] != available[payload.canonical]['kind']:
        raise HTTPException(400, 'Entity types must match')
    try:
        identity = get_store().merge(payload.alias, payload.canonical, payload.reason)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    return {'decision_id': identity}


@router.post('/api/hfl/entities/decisions/{decision_id}/undo')
async def undo(request: Request, decision_id: int):
    actor = authorize(request)
    try:
        await run_in_threadpool(get_store().undo, decision_id, actor)
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc
    return {'undone': decision_id}


@router.post('/api/hfl/entities/export')
async def export(request: Request):
    authorize(request)
    path = os.environ.get('HARQIS_OBSIDIAN_VAULT')
    if not path:
        raise HTTPException(409, 'Configure an optional Obsidian export directory')
    def run():
        from workflows.hfl.obsidian import export_vault
        rows = entities.projection()
        for row in rows:
            row['entities'] = {}
            for m in row['mentions']:
                row['entities'].setdefault(m['kind'], []).append(m['label'] + ' -- ' + m['id'][-8:])
        return export_vault(rows, Path(path))
    return await run_in_threadpool(run)


from modules.hfl_corpus.entity_merge_api import router as entity_merge_router
router.include_router(entity_merge_router)
from modules.hfl_corpus.entity_soul_api import router as entity_soul_router
router.include_router(entity_soul_router)
