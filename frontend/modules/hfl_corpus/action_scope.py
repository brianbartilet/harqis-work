"""Apply the corpus's entry predicates to canonical actions before pagination."""
import asyncio
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from fastapi import HTTPException

from modules.hfl_corpus.view_scope import predicate, request_scope, resolved
from modules.hfl_corpus.workspace_views import WorkspaceState


async def filter_actions(request, items, canonical, *, recent_dismissed=False):
    from modules.hfl_corpus import router as corpus
    from modules.hfl_corpus.timeline import entry_evidence_id

    scope = request_scope(request)
    values = {key: value for key, value in request.query_params.items() if key in WorkspaceState.model_fields}
    try:
        for key in ('rolling', 'page_size'):
            if key in values:
                values[key] = int(values[key])
        state = WorkspaceState.model_validate(values)
    except ValueError:
        raise HTTPException(422, 'Invalid action view filters.') from None
    clauses = [predicate(resolved(value)) for value in scope.any]
    narrowing = predicate(resolved(scope.all if scope.any else state))
    filtered = bool(scope.any or state.q or state.source or state.date_from or state.date_to or state.rolling)
    protected = corpus.normalize_secret_tags(corpus.get_profile_store().get().secret_tags)
    documents = {}
    result = []
    assigned_filter = set(filter(None, request.query_params.get('workspace_ids', '').split(',')))
    selected_views = set(filter(None, request.query_params.get('views', request.query_params.get('workspace', '')).split(',')))
    assigned_state = scope.all if scope.any else state
    if not scope.any and len(selected_views) == 1:
        # Single-workspace URLs flatten the saved filters into the query. Those
        # filters select inherited items, but must not veto explicit membership.
        from modules.hfl_corpus.workspace_views import listing
        view = next((view for view in listing()['views'] if view['id'] in selected_views), None)
        if view:
            defaults = WorkspaceState().model_dump()
            assigned_state = WorkspaceState.model_validate({
                key: defaults[key] if value == view['state'].get(key, defaults[key]) else value
                for key, value in state.model_dump().items()
            })
            # The date field still defines any additional date constraints.
            assigned_state.date_field = state.date_field
    assigned_narrowing = predicate(resolved(assigned_state))
    for original in items:
        item = dict(original)
        assignments = set(item.get('workspace_ids', []))
        if assigned_filter and not assignments.intersection(assigned_filter):
            continue
        explicitly_selected = bool(assignments.intersection(selected_views))
        if recent_dismissed and item['status'] == 'dismissed':
            history = sorted(canonical.history(item['id']), key=lambda row: row['item']['version'])
            dismissed_at, previous = None, None
            for row in history:
                status = row['item']['status']
                if status == 'dismissed' and previous != status:
                    dismissed_at = datetime.fromisoformat(row['changed_at'])
                previous = status
            if dismissed_at is None or dismissed_at < datetime.now(timezone.utc) - timedelta(days=14):
                continue
        source = item.get('source')
        if source:
            path = source['path']
            if path not in documents:
                if corpus._uses_remote_corpus():
                    try:
                        documents[path], _ = await asyncio.to_thread(
                            corpus.RemoteCorpusClient.from_settings().document, path,
                            include_secrets=False, secret_tags=protected)
                    except corpus.RemoteCorpusError:
                        raise HTTPException(502, 'Action evidence could not be loaded. Retry shortly.') from None
                else:
                    documents[path] = await asyncio.to_thread(corpus.corpus_index.get, path)
            document = documents[path]
            entry = next((entry for entry in document.entries if entry_evidence_id(entry.text) == source['entry_id']), None) if document else None
            if entry and corpus.is_secret_entry(entry, protected):
                continue
            item['sources'] = [entry.source] if entry else []
            item['evidence_available'] = entry is not None
            if not entry:
                if filtered:
                    continue
                result.append(item)
                continue
        else:
            item['sources'] = ['manual-entry']
            item['evidence_available'] = False
            document = SimpleNamespace(**{field: datetime.fromisoformat(item[field]) for field in ('created_at', 'updated_at')})
            entry = SimpleNamespace(source='manual-entry', tags=(), text=item['title']+'\n'+item.get('expected_outcome', '')+'\n'+item.get('body', ''), header='', occurrence_date=None)
            # No entry exists, so entry-date constraints cannot be satisfied.
            states = [scope.all if scope.any else state, *scope.any]
            def manual_matches(value):
                values = resolved(value)
                if values.get('date_field') == 'entry' and (values.get('date_from') or values.get('date_to')):
                    return False
                return predicate(values)(document, entry)
            if not manual_matches(assigned_state if explicitly_selected else states[0]) or (scope.any and not explicitly_selected and not any(manual_matches(value) for value in scope.any)):
                continue
            result.append(item)
            continue
        matches_narrowing = assigned_narrowing if explicitly_selected else narrowing
        if matches_narrowing(document, entry) and (explicitly_selected or not clauses or any(match(document, entry) for match in clauses)):
            result.append(item)
    return result
