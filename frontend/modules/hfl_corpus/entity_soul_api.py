"""Owner-only soul editing and compact agent context."""
from typing import Literal
from uuid import uuid4

from fastapi import APIRouter, HTTPException, Request, BackgroundTasks
from pydantic import BaseModel, ConfigDict, Field, model_validator
from starlette.concurrency import run_in_threadpool

router = APIRouter(prefix='/api/hfl/entities')


class Record(BaseModel):
    model_config = ConfigDict(extra='forbid')
    id: str = Field(default_factory=lambda: uuid4().hex, min_length=1, max_length=500)


class IdentityRule(Record):
    observed_name: str = Field(min_length=2, max_length=120)
    sources: list[str] = Field(min_length=1, max_length=30)
    required_context: list[str] = Field(default_factory=list, max_length=20)
    excluded_context: list[str] = Field(default_factory=list, max_length=20)
    enabled: bool = True

    @model_validator(mode='after')
    def scope(self):
        for field in ('sources', 'required_context', 'excluded_context'):
            values = list(dict.fromkeys(v.strip() for v in getattr(self, field)))
            if any(not v or len(v) > 200 or v == '*' for v in values):
                raise ValueError('Use explicit nonempty source names and context phrases, not wildcards')
            setattr(self, field, values)
        self.observed_name = self.observed_name.strip()
        if len(self.observed_name) < 2:
            raise ValueError('Enter an observed name')
        return self


class Relationship(Record):
    target_id: str = Field(min_length=1, max_length=200)
    relation: Literal['colleague_of', 'works_at', 'member_of', 'owns', 'uses', 'related_to']
    since: str = Field(default='', pattern=r'^(\d{4}-\d{2}-\d{2})?$')
    until: str = Field(default='', pattern=r'^(\d{4}-\d{2}-\d{2})?$')
    evidence: str = Field(default='', max_length=2000)

    @model_validator(mode='after')
    def dates(self):
        from datetime import date
        for value in (self.since, self.until):
            if value:
                date.fromisoformat(value)
        if self.since and self.until and self.until < self.since:
            raise ValueError('End date must follow start date')
        return self


class JournalEntry(Record):
    text: str = Field(min_length=1, max_length=4000)


class SoulWrite(BaseModel):
    model_config = ConfigDict(extra='forbid')
    version: int = Field(ge=0)
    markdown: str = Field(default='', max_length=20000)
    identity_rules: list[IdentityRule] = Field(default_factory=list, max_length=100)
    relationships: list[Relationship] = Field(default_factory=list, max_length=100)
    journal: list[JournalEntry] = Field(default_factory=list, max_length=200)

    @model_validator(mode='after')
    def unique(self):
        for field in ('identity_rules', 'relationships', 'journal'):
            rows = getattr(self, field)
            if len({r.id for r in rows}) != len(rows):
                raise ValueError('Record IDs must be unique')
        return self


def snapshot():
    from modules.hfl_corpus.entities import entity_index
    return {e['id']: e for e in entity_index()}


@router.get('/context/{identity}')
async def read_context(request: Request, identity: str):
    from modules.hfl_corpus.entities_api import authorize
    from workflows.hfl import entity_soul
    from services.markdown import render_markdown
    authorize(request)
    available = await run_in_threadpool(snapshot)
    if identity not in available:
        raise HTTPException(404, 'Entity unavailable')
    result = await run_in_threadpool(entity_soul.context, available[identity], available)
    result['soul_html'] = str(render_markdown(result['soul']['markdown']))
    return result


@router.post('/soul/{identity}')
async def write_soul(request: Request, identity: str, payload: SoulWrite, background_tasks: BackgroundTasks):
    from modules.hfl_corpus.entities_api import authorize
    from workflows.hfl import entity_soul, entity_resolution
    actor = authorize(request)
    available = await run_in_threadpool(snapshot)
    try:
        result = await run_in_threadpool(entity_soul.save, identity, payload.model_dump(), actor, available)
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc
    background_tasks.add_task(entity_resolution.dispatch_pending)
    return {'soul': result}


@router.post('/resolutions/{entry_id}/{mention_id}/undo')
async def undo_resolution(request: Request, entry_id: str, mention_id: str):
    from modules.hfl_corpus.entities_api import authorize
    from workflows.hfl.entity_resolution import undo
    actor = authorize(request)
    try:
        return await run_in_threadpool(undo, entry_id, mention_id, actor)
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc


class ConnectionChange(Relationship):
    source_id: str = Field(default='', max_length=200)
    activity: bool = False
    remove: bool = False


class ConnectionsWrite(BaseModel):
    model_config = ConfigDict(extra='forbid')
    changes: list[ConnectionChange] = Field(max_length=100)
    versions: dict[str, int]


@router.get('/connections/{identity}')
async def read_connections(request: Request, identity: str):
    from modules.hfl_corpus.entities_api import authorize
    authorize(request)
    return await run_in_threadpool(connection_snapshot, identity)


def connection_snapshot(identity, available=None, connection=None, entries=None):
    from workflows.hfl.entity_soul import all_souls
    from workflows.hfl.entity_store import get_store
    from workflows.hfl.entity_connections import activity_links
    from modules.hfl_corpus.entities import current_entries
    available = snapshot() if available is None else available
    if identity not in available:
        raise HTTPException(404, 'Entity unavailable')
    from contextlib import nullcontext
    from workflows.hfl.entity_store import identity_resolver
    entries = {e['id']: e for e in current_entries()} if entries is None else entries
    with (nullcontext(connection) if connection is not None else get_store().connection()) as db:
        resolve = identity_resolver(db)
        souls = all_souls(db)
        links = []
        versions = {identity: souls.get(identity, {}).get('version', 0)}
        for source, soul in souls.items():
            if source not in available or resolve(source) != source:
                continue
            for row in soul['relationships']:
                target = resolve(row['target_id'])
                if target not in available or identity not in (source, target) or source == target:
                    continue
                other = available[target if source == identity else source]
                links.append({**row, 'source_id': source, 'target_id': target, 'label': other['label'],
                              'kind': other['kind'], 'other_id': other['id'], 'incoming': source != identity, 'activity': False})
                versions[source] = soul['version']
        seen_entries = set()
        for row in activity_links(db):
            if resolve(row['entity_id']) != identity or row['entry_id'] not in entries:
                continue
            if row['entry_id'] in seen_entries:
                continue
            seen_entries.add(row['entry_id'])
            entry = entries[row['entry_id']]
            links.append(dict(id='activity:' + entry['id'], source_id=identity, target_id=entry['id'],
                              other_id='entry:' + entry['id'], label=entry['title'], kind='entries', activity=True,
                              relation='related_to', since='', until='', evidence='', incoming=False))
        return {'entity': available[identity], 'connections': links, 'versions': versions}


@router.post('/connections/{identity}')
async def write_connections(request: Request, identity: str, payload: ConnectionsWrite):
    from modules.hfl_corpus.entities_api import authorize
    from modules.hfl_corpus.entities import current_entries
    from workflows.hfl.entity_connections import edit
    actor = authorize(request)
    available = await run_in_threadpool(snapshot)
    entries = await run_in_threadpool(current_entries)
    try:
        return await run_in_threadpool(edit, identity, [c.model_dump() for c in payload.changes],
                                       actor, available, {e['id'] for e in entries}, payload.versions)
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc


@router.get('/connection-activities')
async def activity_options(request: Request, q: str = ''):
    from modules.hfl_corpus.entities_api import authorize
    from modules.hfl_corpus.entities import current_entries
    authorize(request)
    entries = await run_in_threadpool(current_entries)
    rows = [e for e in entries if all(w in (e['title'] + ' ' + e['date']).casefold() for w in q.casefold().split())]
    rows.sort(key=lambda e: (e['date'], e['id']), reverse=True)
    return {'total': len(rows), 'entities': [dict(id=e['id'], label=e['title'], kind='entries', date=e['date']) for e in rows[:50]]}


class OwnerBinding(BaseModel):
    identity: str


@router.post('/owner-binding')
async def bind_owner(request: Request, payload: OwnerBinding):
    from modules.hfl_corpus.entities_api import authorize
    from modules.hfl_corpus.entity_owner import synchronize
    authorize(request)
    available = await run_in_threadpool(snapshot)
    try:
        return await run_in_threadpool(synchronize, available, payload.identity)
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc


class SoulEditorWrite(BaseModel):
    model_config = ConfigDict(extra='forbid')
    revision: str
    profile: dict
    soul: SoulWrite
    connections: ConnectionsWrite
    new_entities: list[dict] = Field(default_factory=list, max_length=100)


def editor_revision(db, identity):
    """Include incoming relationships and activity links in the conflict token."""
    import json
    from workflows.hfl.entity_store import digest
    profile = db.execute('SELECT kind,data FROM profiles WHERE id=?', (identity,)).fetchone()
    related = []
    for row in db.execute('SELECT id,version,data FROM entity_souls ORDER BY id'):
        if row['id'] == identity or any(r['target_id'] == identity for r in json.loads(row['data'])['relationships']):
            related.append(tuple(row))
    links = [tuple(r) for r in db.execute('SELECT * FROM entity_activity_links WHERE entity_id=? ORDER BY entry_id', (identity,))]
    return digest([tuple(profile) if profile else None, related, links])


def editor_snapshot(identity):
    from workflows.hfl.entity_store import get_store
    from workflows.hfl.entity_soul import all_souls, empty
    from services.markdown import render_markdown
    from modules.hfl_corpus.entities import current_entries
    available = snapshot()
    entries = {e['id']: e for e in current_entries()}
    with get_store().connection() as db:
        db.execute('BEGIN')
        result = connection_snapshot(identity, available, db, entries)
        profile = db.execute('SELECT data FROM profiles WHERE id=?', (identity,)).fetchone()
        if profile:
            import json
            result['entity']['profile'] = json.loads(profile[0])
        result['soul'] = all_souls(db).get(identity, empty())
        result['soul_html'] = str(render_markdown(result['soul']['markdown']))
        result['revision'] = editor_revision(db, identity)
        return result


@router.get('/soul-editor/{identity}')
async def read_soul_editor(request: Request, identity: str):
    from modules.hfl_corpus.entities_api import authorize
    authorize(request)
    return await run_in_threadpool(editor_snapshot, identity)


def save_editor(identity, payload, actor):
    from modules.hfl_corpus.entities_api import Profile, TypedProfile, validated_profile
    from modules.hfl_corpus.entities import current_entries
    from workflows.hfl.entity_store import get_store
    from workflows.hfl import entity_soul, entity_connections, entity_types
    from pydantic import ValidationError
    try:
        profile = validated_profile(Profile(**payload.profile))
        new_entities = [(r['id'], TypedProfile(**{k:v for k,v in r.items() if k != 'id'})) for r in payload.new_entities]
    except (ValidationError, KeyError) as exc:
        raise HTTPException(422, 'Check Profile details and new entity names.') from exc
    available = snapshot()
    if identity not in available:
        raise ValueError('Entity unavailable; reopen the dialog.')
    if available[identity].get('is_owner') and profile['name'] != available[identity]['label']:
        raise ValueError('Update your owner name in /profile.')
    entry_ids = {e['id'] for e in current_entries()}
    kinds = {t['id'] for t in entity_types.listing()}
    store = get_store()
    with store.connection() as db:
        db.execute('BEGIN IMMEDIATE')
        if editor_revision(db, identity) != payload.revision:
            raise ValueError('Entity details changed. Your edits are retained; reopen the dialog to load the latest values.')
        for new_id, item in new_entities:
            import re
            if not re.fullmatch(r'manual-[0-9a-f-]{36}', new_id) or new_id in available or item.kind not in kinds:
                raise ValueError('New entity changed or has an invalid type.')
            data = validated_profile(Profile(**item.model_dump(exclude={'kind'})))
            if any(e['kind'] == item.kind and e['label'].casefold() == data['name'].casefold() for e in available.values()):
                raise ValueError('A matching entity now exists; choose it in Connections.')
            store.save_profile(new_id, item.kind, data, actor, connection=db)
            available[new_id] = dict(id=new_id, label=data['name'], kind=item.kind)
        store.save_profile(identity, available[identity]['kind'], profile, actor, connection=db)
        # Connection edits preserve relationship provenance; identity saves read their final values.
        entity_connections.edit(identity, [c.model_dump() for c in payload.connections.changes], actor,
                                available, entry_ids, payload.connections.versions, connection=db)
        latest = entity_soul.all_souls(db).get(identity, entity_soul.empty())
        data = payload.soul.model_dump()
        if payload.soul.version != payload.connections.versions.get(identity):
            raise ValueError('Identity details changed; reopen the dialog.')
        data['version'] = latest['version']
        data['relationships'] = [{k:v for k,v in r.items() if k != 'provenance'} for r in latest['relationships']]
        entity_soul.save(identity, data, actor, available, connection=db)
    return {'saved': True}


@router.post('/soul-editor/{identity}')
async def write_soul_editor(request: Request, identity: str, payload: SoulEditorWrite, background_tasks: BackgroundTasks):
    from modules.hfl_corpus.entities_api import authorize
    from workflows.hfl.entity_resolution import dispatch_pending
    actor = authorize(request)
    try:
        result = await run_in_threadpool(save_editor, identity, payload, actor)
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc
    background_tasks.add_task(dispatch_pending)
    return result
