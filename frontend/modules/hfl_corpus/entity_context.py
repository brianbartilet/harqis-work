"""Apply the same entry-level workspace semantics to graph and directory reads."""
from urllib.parse import parse_qsl

from fastapi import HTTPException
from modules.hfl_corpus.view_scope import parse_scope, predicate, resolved
from modules.hfl_corpus.workspace_views import WorkspaceState


def context_predicate(context):
    if not context:
        return None
    try:
        if len(context) > 120_000:
            raise ValueError('Context too large')
        params = dict(parse_qsl(context))
        scope = parse_scope(params.get('scope', ''))
        values = {key: value for key, value in params.items() if key in WorkspaceState.model_fields}
        for key in ('rolling', 'page_size'):
            if key in values:
                values[key] = int(values[key])
        state = WorkspaceState.model_validate({**scope.all.model_dump(), **values})
        narrowing = predicate(resolved(state))
        clauses = [predicate(resolved(value)) for value in scope.any]
    except ValueError as exc:
        raise HTTPException(422, 'Invalid inherited activity filters.') from exc
    return lambda document, entry: narrowing(document, entry) and (
        not clauses or any(clause(document, entry) for clause in clauses))
