"""Entry-level union of view filters, shared by corpus and sharing."""
import json
from collections import Counter
from dataclasses import replace
from datetime import date, timedelta
from pydantic import BaseModel, ConfigDict, Field
from modules.hfl_corpus.workspace_views import WorkspaceState
from modules.hfl_corpus.corpus import entry_occurrence_date, parse_search_query


class ViewScope(BaseModel):
    model_config = ConfigDict(extra='forbid')
    any: list[WorkspaceState] = Field(default_factory=list, max_length=30)
    all: WorkspaceState = Field(default_factory=WorkspaceState)


def parse_scope(raw):
    if not raw:
        return ViewScope()
    if len(raw) > 100_000:
        raise ValueError('Combined view is too large.')
    return ViewScope.model_validate_json(raw)


def resolved(state, today=None):
    values = state.model_dump() if isinstance(state, WorkspaceState) else dict(state)
    if values.get('rolling'):
        today = today or date.today()
        values.update(date_from=(today-timedelta(days=values['rolling']-1)).isoformat(), date_to=today.isoformat(), rolling=0)
    return values


def matches(document, entry, state):
    tags, phrase = parse_search_query(state.get('q', ''))
    if not all(any(needle in tag.casefold() for tag in entry.tags) for needle in tags):
        return False
    if phrase and phrase not in entry.text.casefold():
        return False
    sources = {s.strip().casefold() for s in state.get('source', '').split(',') if s.strip()}
    if sources and entry.source.strip().casefold() not in sources:
        return False
    when = entry_occurrence_date(entry) if state.get('date_field') == 'entry' else getattr(document, state.get('date_field', 'created')+'_at').date()
    start, end = state.get('date_from'), state.get('date_to')
    return not ((start and (when is None or when < date.fromisoformat(start))) or (end and (when is None or when > date.fromisoformat(end))))


def filter_scope(documents, scope):
    if not scope.any:
        return documents
    clauses = [resolved(s) for s in scope.any]
    narrowing = resolved(scope.all)
    result = []
    for document in documents:
        entries = tuple(entry for entry in document.entries if matches(document, entry, narrowing) and any(matches(document, entry, clause) for clause in clauses))
        if entries:
            tags = Counter(tag for entry in entries for tag in entry.tags)
            result.append(replace(document, entries=entries, entry_count=len(entries), matching_entry_count=len(entries),
                text='\n'.join(entry.text for entry in entries), tags=tuple(tags), tag_counts=tuple(tags.items()),
                tag_entry_anchors=tuple((tag, entry.anchor) for entry in entries for tag in entry.tags)))
    return tuple(result)


def request_scope(request):
    from fastapi import HTTPException
    try:
        scope = parse_scope(request.query_params.get('scope', ''))
        if scope.any:
            overrides = {key: value for key, value in request.query_params.items() if key in WorkspaceState.model_fields}
            scope.all = WorkspaceState.model_validate({**scope.all.model_dump(), **overrides})
        return scope
    except ValueError as exc:
        raise HTTPException(422, 'Invalid combined view filters.') from exc
