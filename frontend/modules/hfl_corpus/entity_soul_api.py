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
