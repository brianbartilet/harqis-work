"""Owner-only Activity Corpus graph, entity timelines, and enrichment controls."""
from pathlib import Path
import os
from fastapi import APIRouter, HTTPException, Request, Query
from fastapi.responses import RedirectResponse
from pydantic import BaseModel, Field
from starlette.concurrency import run_in_threadpool
from auth import get_current_user
from web import templates, page_context, require_user
from modules.hfl_corpus import entities
from workflows.hfl.entity_store import get_store

router = APIRouter()


def authorize(request):
    if not get_current_user(request):
        raise HTTPException(401, 'Sign in to view corpus relationships')


@router.get('/knowledge')
@router.get('/knowledge/graph')
async def legacy(request: Request):
    return RedirectResponse('/hfl-corpus/graph' + ('?' + request.url.query if request.url.query else ''), 307)


@router.get('/hfl-corpus/graph')
@router.get('/hfl-corpus/entities')
async def page(request: Request):
    user, redirect = require_user(request)
    if redirect:
        return redirect
    template = 'knowledge_graph.html' if request.url.path.endswith('/graph') else 'entities.html'
    return templates.TemplateResponse(request, 'modules/hfl_corpus/' + template,
                                      page_context(request, user, 'hfl_corpus'))


@router.get('/api/hfl/entities/graph')
async def graph(request: Request, source: str = '', since: str = '', until: str = '',
                limit: int = Query(default=100, ge=1, le=1000),
                query: str = Query(default='', max_length=200), shared: bool = False,
                sources: list[str] = Query(default=[])):
    authorize(request)
    return await run_in_threadpool(entities.graph, sources or source, since, until, limit, query, shared)


@router.get('/api/hfl/entities')
async def index(request: Request, source: str = '', since: str = '', until: str = '',
                limit: int | None = Query(default=None, ge=1, le=10000)):
    authorize(request)
    rows = await run_in_threadpool(entities.entity_index, source, since, until)
    rows.sort(key=lambda e: (e['label'].casefold(), e['id']))
    return {'entities': rows[:limit] if limit else rows, 'total': len(rows)}


class Profile(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    categories: list[str] = Field(default_factory=list, max_length=20)
    emails: list[str] = Field(default_factory=list, max_length=20)
    phones: list[str] = Field(default_factory=list, max_length=20)
    notes: str = Field(default='', max_length=10000)


@router.post('/api/hfl/entities/profile/{identity}')
async def save_profile(request: Request, identity: str, payload: Profile):
    authorize(request)
    data = payload.model_dump()
    data['name'] = data['name'].strip()
    if not data['name'] or entities.is_link(data['name']):
        raise HTTPException(400, 'Use an entity name, not a link or email address')
    for field in ('categories', 'emails', 'phones'):
        data[field] = list(dict.fromkeys(v.strip() for v in data[field] if v.strip()))
        if any(len(v) > 200 for v in data[field]):
            raise HTTPException(400, 'Contact details and categories must be at most 200 characters each')
    import re
    if any(not re.fullmatch(r'[^\s@]+@[^\s@]+\.[^\s@]+', v) for v in data['emails']):
        raise HTTPException(400, 'Enter valid email addresses, one per line')
    if any(not re.fullmatch(r'[+()0-9 .xX#-]{3,80}', v) or sum(c.isdigit() for c in v) < 3 for v in data['phones']):
        raise HTTPException(400, 'Enter phone numbers, one per line')
    available = {e['id']: e for e in await run_in_threadpool(entities.entity_index)}
    if identity not in available:
        raise HTTPException(404, 'Entity unavailable')
    get_store().save_profile(identity, available[identity]['kind'], data)
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
            item = dict(title=entry.moment, text=entry.text, date=occurred.isoformat() if occurred else '', source=entry.source)
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
    return {'title': item['title'], 'date': item['date'], 'source': item['source'], 'html': str(html)}


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
    return {'job': store.state('job'), 'enrichment': store.state('enrichment'),
            'decisions': store.decisions()}


@router.post('/api/hfl/entities/backfill')
async def backfill(request: Request):
    authorize(request)
    from workflows.hfl.entity_events import request_enrichment
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
    authorize(request)
    get_store().undo(decision_id)
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
