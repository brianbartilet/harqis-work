"""Entry-level union of view filters, shared by corpus and sharing."""
from collections import Counter
from dataclasses import replace
from datetime import date, datetime, timedelta, timezone
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
    if values.get('rolling') == 1:
        values.update(date_from='', date_to='')
        return values
    if values.get('rolling'):
        today = today or date.today()
        values.update(date_from=(today-timedelta(days=values['rolling']-1)).isoformat(), date_to=today.isoformat(), rolling=0)
    return values


def predicate(state):
    """Compile tag/source/date filters once, rather than once per entry."""
    from modules.hfl_corpus.expressions import compile_expression, has_media, normalize_tags
    expression_matches = compile_expression(state.get('expression', ''))
    excluded = set(normalize_tags(state.get('exclude_tags', '')).split(',')) - {''}
    tags, phrase = parse_search_query(state.get('q', ''))
    sources = {s.strip().casefold() for s in state.get('source', '').split(',') if s.strip()}
    start = date.fromisoformat(state['date_from']) if state.get('date_from') else None
    end = date.fromisoformat(state['date_to']) if state.get('date_to') else None
    field = state.get('date_field', 'created')
    now = datetime.now(timezone.utc)
    recent = state.get('rolling') == 1
    nested = parse_scope(state.get('entry_scope', ''))
    nested_any = [predicate(resolved(item)) for item in nested.any]
    nested_all = predicate(resolved(nested.all)) if state.get('entry_scope') else None

    def matches(document, entry):
        if recent:
            try:
                when = datetime.fromisoformat(entry.header.strip()) if field == 'entry' else getattr(document, field+'_at')
                when = when.astimezone(timezone.utc)
                if not now-timedelta(hours=24) <= when <= now:
                    return False
            except (ValueError, TypeError):
                return False
        if not expression_matches(document, entry):
            return False
        if excluded.intersection(tag.casefold().lstrip('#') for tag in entry.tags):
            return False
        if state.get('has_media') and not has_media(entry):
            return False
        if nested_all and not (nested_all(document, entry) and (not nested_any or any(check(document, entry) for check in nested_any))):
            return False
        if sources and entry.source.strip().casefold() not in sources:
            return False
        if not all(any(needle in tag.casefold() for tag in entry.tags) for needle in tags):
            return False
        if phrase and phrase not in entry.text.casefold():
            return False
        if start or end:
            when = entry_occurrence_date(entry) if field == 'entry' else getattr(document, field+'_at').date()
            if when is None or (start and when < start) or (end and when > end):
                return False
        return True
    return matches


def filter_scope(documents, scope):
    selection_keys = ('q', 'source', 'date_from', 'date_to', 'rolling', 'entry_scope', 'has_media', 'exclude_tags', 'expression')
    constrained = lambda state: any(getattr(state, key) for key in selection_keys)
    if scope.all.order_by and not constrained(scope.all) and (not scope.any or any(not constrained(state) for state in scope.any)):
        from modules.hfl_corpus.ordering import sorted_documents
        return tuple(sorted_documents(documents, scope.all.order_by))
    if not scope.any and not any(getattr(scope.all, key) for key in ('q', 'source', 'date_from', 'date_to', 'rolling', 'entry_scope', 'has_media', 'exclude_tags', 'expression', 'order_by')):
        return documents
    clauses = [predicate(resolved(s)) for s in scope.any]
    narrowing = predicate(resolved(scope.all))
    result = []
    for document in documents:
        entries = tuple(entry for entry in document.entries if narrowing(document, entry) and (not clauses or any(clause(document, entry) for clause in clauses)))
        if entries:
            tags = Counter(tag for entry in entries for tag in entry.tags)
            result.append(replace(document, entries=entries, entry_count=len(entries), matching_entry_count=len(entries),
                text='\n'.join(entry.text for entry in entries), tags=tuple(tags), tag_counts=tuple(tags.items()),
                tag_entry_anchors=tuple((tag, entry.anchor) for entry in entries for tag in entry.tags)))
    if scope.all.order_by:
        from modules.hfl_corpus.ordering import sorted_documents
        result = sorted_documents(result, scope.all.order_by)
    return tuple(result)


def request_scope(request):
    from fastapi import HTTPException
    try:
        scope = parse_scope(request.query_params.get('scope', ''))
        if not request.query_params.get('scope') and request.query_params.get('entry_scope'):
            scope = ViewScope(any=[WorkspaceState(entry_scope=request.query_params['entry_scope'])])
        advanced = {key: request.query_params[key] for key in ('has_media', 'exclude_tags', 'expression', 'order_by') if key in request.query_params}
        validated = WorkspaceState.model_validate(advanced)
        if (validated.has_media or validated.exclude_tags or validated.expression or validated.order_by) and not scope.any:
            scope.any = [WorkspaceState()]
        if scope.any or request.query_params.get('scope'):
            overrides = {key: value for key, value in request.query_params.items() if key in WorkspaceState.model_fields}
            # Query strings carry text; numeric Literal fields require integers.
            for key in ('page_size', 'rolling'):
                if key in overrides:
                    overrides[key] = int(overrides[key])
            merged = {**scope.all.model_dump(), **overrides}
            if 'order_by' in overrides and 'sort' not in overrides:
                merged.pop('sort', None)
            scope.all = WorkspaceState.model_validate(merged)
        return scope
    except ValueError as exc:
        raise HTTPException(422, 'Invalid combined view filters.') from exc
