"""Space membership for owner graphs; never an authorization boundary.

Recipient sharing will separately validate access before including complete boards.
"""
import asyncio
from types import SimpleNamespace
from starlette.datastructures import QueryParams


def active_context(context):
    """Empty All activity URLs must behave like an unfiltered graph."""
    from modules.hfl_corpus.entity_context import context_predicate
    from modules.hfl_corpus.view_scope import parse_scope

    context_predicate(context)
    params = QueryParams(context)
    scope = parse_scope(params.get('scope', ''))
    values = {**scope.all.model_dump(), **dict(params)}
    active = scope.any or any(values.get(key) for key in ('workspace', 'views', 'q', 'source', 'date_from', 'date_to'))
    return context if active or int(values.get('rolling') or 0) else ''


def scope_snapshot(snapshot, context):
    """Reuse Corpus/Kanban predicates, including explicit intent assignments."""
    if not context:
        return snapshot
    from modules.hfl_corpus.action_scope import filter_actions
    from modules.hfl_corpus.entity_context import context_predicate

    context_predicate(context)  # Validate before parsing or loading intent evidence.

    params = QueryParams(context)
    selected = set(filter(None, params.get('views', params.get('workspace', '')).split(',')))
    request = SimpleNamespace(query_params=params)

    async def intents():
        return {kind: await filter_actions(request, snapshot.get(kind, []), None)
                for kind in ('ideas', 'actions')}

    result = {**snapshot, **asyncio.run(intents())}
    result['maps'] = [board for board in snapshot.get('maps', [])
                      if not selected or selected.intersection(board.get('workspace_ids', []))]
    # Only eligible objects can participate in traversal through manual links.
    excluded = set()
    for kind, prefix in [('ideas', 'idea:'), ('actions', 'action:'), ('maps', 'board:')]:
        retained = {row['id'] for row in result.get(kind, [])}
        excluded.update(prefix + item['id'] for item in snapshot.get(kind, []) if item['id'] not in retained)
    result['links'] = [edge for edge in snapshot.get('links', [])
                       if edge['source'] not in excluded and edge['target'] not in excluded]
    return result
