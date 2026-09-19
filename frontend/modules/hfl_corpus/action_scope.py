"""Apply the corpus's entry predicates to canonical actions before pagination."""
import asyncio
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from modules.hfl_corpus.view_scope import predicate, request_scope, resolved
from modules.hfl_corpus.workspace_views import WorkspaceState


async def filter_actions(request, items, canonical, *, recent_dismissed=False):
    from modules.hfl_corpus import router as corpus
    from modules.hfl_corpus.timeline import entry_guid

    scope = request_scope(request)
    values = {key: value for key, value in request.query_params.items() if key in WorkspaceState.model_fields}
    for key in ('rolling', 'page_size'):
        if key in values:
            values[key] = int(values[key])
    state = WorkspaceState.model_validate(values)
    clauses = [predicate(resolved(value)) for value in scope.any]
    narrowing = predicate(resolved(scope.all if scope.any else state))
    filtered = bool(scope.any or state.q or state.source or state.date_from or state.date_to or state.rolling)
    protected = corpus.normalize_secret_tags(corpus.get_profile_store().get().secret_tags)
    documents = {}
    result = []
    for original in items:
        item = dict(original)
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
                    documents[path], _ = await asyncio.to_thread(
                        corpus.RemoteCorpusClient.from_settings().document, path,
                        include_secrets=False, secret_tags=protected)
                else:
                    documents[path] = corpus.corpus_index.get(path)
            document = documents[path]
            entry = next((entry for entry in document.entries if entry_guid(entry) == source['entry_id']), None) if document else None
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
            entry = SimpleNamespace(source='manual-entry', tags=(), text=item['title']+'\n'+item['expected_outcome'], header='', occurrence_date=None)
            # No entry exists, so entry-date constraints cannot be satisfied.
            states = [scope.all if scope.any else state, *scope.any]
            def manual_matches(value):
                values = resolved(value)
                if values.get('date_field') == 'entry' and (values.get('date_from') or values.get('date_to')):
                    return False
                return predicate(values)(document, entry)
            if not manual_matches(states[0]) or (scope.any and not any(manual_matches(value) for value in scope.any)):
                continue
            result.append(item)
            continue
        if narrowing(document, entry) and (not clauses or any(match(document, entry) for match in clauses)):
            result.append(item)
    return result
