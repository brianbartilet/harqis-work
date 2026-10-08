"""Publication projection. Never serialize owner graphs or canonical objects directly."""
from dataclasses import replace
import hashlib
import json
import re

import httpx

from config import get_settings
from modules.hfl_shares.activity_models import selection
from modules.hfl_shares.models import SnapshotEntry, SnapshotReference


def load_context():
    from modules.hfl_corpus.ideas_api import store
    settings = get_settings()
    if not settings.hfl_corpus_api_url:
        return {**store().snapshot(), 'plans': load_plans()}
    try:
        response = httpx.get(settings.hfl_corpus_api_url.rstrip('/') + '/api/hfl/timeline/ideas/share-context',
                            headers={'Authorization': 'Bearer ' + settings.hfl_corpus_api_token}, timeout=45)
        legacy = response.status_code == 404
        if legacy:
            response = httpx.get(settings.hfl_corpus_api_url.rstrip('/') + '/api/hfl/timeline/ideas/snapshot',
                                headers={'Authorization': 'Bearer ' + settings.hfl_corpus_api_token}, timeout=45)
        response.raise_for_status()
        data = response.json()
        data['_secrets_supported'] = not legacy
        return data
    except (httpx.HTTPError, ValueError) as exc:
        raise ValueError('Workspace sharing context could not load. The canonical API must support workspace sharing.') from exc


def load_plans():
    """Project active pin categories into shareable dates without agent metadata."""
    from modules.hfl_corpus.memory_pins import get_memory_pin_store, PIN_COLORS
    pins = get_memory_pin_store().snapshot()
    categories = {c['id']: c for c in pins['categories']}
    return [dict(id=str(pin['id']), title=pin['title'], start_date=pin['start_date'],
                 end_date=pin['end_date'], description=pin['prompt'], notes=pin['note'],
                 updated_at=pin['updated_at'], category=categories[pin['category_id']]['name'],
                 color=categories[pin['category_id']]['color'] if categories[pin['category_id']]['color'] in PIN_COLORS else PIN_COLORS[0],
                 workspace_ids=categories[pin['category_id']]['workspace_ids'])
            for pin in pins['ranges'] if pin['category_id'] in categories]


def mentions_for_documents(documents):
    """Use only current entry-matched extraction records, without a second corpus scan."""
    from modules.hfl_corpus.entities import entry_hash, explicit_mentions
    from modules.hfl_corpus.corpus import entry_occurrence_date
    from modules.hfl_shares.scope import _entry_key
    from workflows.hfl.entity_store import get_store, VERSION
    settings = get_settings()
    if settings.hfl_corpus_api_url:
        try:
            response = httpx.get(settings.hfl_corpus_api_url.rstrip('/') + '/api/hfl/entities/graph',
                                params={'limit': 0}, headers={'Authorization': 'Bearer ' + settings.hfl_corpus_api_token}, timeout=60)
            response.raise_for_status()
            graph = response.json()
            nodes = {n['id']: n for n in graph['nodes']}
            texts = {_entry_key(d, e.anchor, e.text): e.text for d in documents for e in d.entries}
            grouped = {}
            for edge in graph['edges']:
                if edge.get('relation') == 'mentions' and edge['source'].startswith('entry:') and edge['target'] in nodes:
                    evidence = edge.get('evidence', '')
                    if not evidence or not all(part in texts.get(edge['source'][6:], '') for part in evidence.split('\n\n')):
                        continue
                    node = nodes[edge['target']]
                    grouped.setdefault(edge['source'][6:], []).append({k: node[k] for k in ('id', 'label', 'kind')})
            for identity, mentions in grouped.items():
                yield {'id': identity, 'mentions': mentions}
            return
        except (httpx.HTTPError, ValueError, KeyError) as exc:
            raise ValueError('Activity graph could not load from the canonical host. Retry before generating the share.') from exc
    store = get_store()
    records, profiles = store.records(), store.profiles()
    aliases = {d['alias']: d['canonical'] for d in store.decisions() if d['active']}
    for document in documents:
        for entry in document.entries:
            when = entry_occurrence_date(entry)
            if when is None:
                continue
            row = {'id': _entry_key(document, entry.anchor, entry.text), 'text': entry.text,
                   'source': entry.source, 'date': when.isoformat(), 'tags': list(entry.tags)}
            cached = records.get(row['id'], {})
            valid = cached.get('hash') == entry_hash(row) and cached.get('version') in {VERSION, VERSION + '-explicit'}
            mentions = cached.get('mentions', []) if valid else explicit_mentions(row)
            resolved = []
            for mention in mentions:
                identity, visited = mention['id'], set()
                while identity in aliases and identity not in visited:
                    visited.add(identity)
                    identity = aliases[identity]
                profile = profiles.get(identity, {})
                resolved.append({**mention, 'id': identity, 'label': profile.get('name', mention['label']),
                                 'kind': profile.get('kind', mention['kind'])})
            yield {**row, 'mentions': resolved}


def safe_text(value):
    from modules.hfl_shares.scope import _sanitize_entry_text
    # URLs are delivered through individually approved references, never inline.
    text = re.sub(r'!?\[([^\]]*)\]\([^)]*\)', r'\1', str(value or ''))
    text = re.sub(r'https?://[^\s<>]+', '[reference]', text)
    return _sanitize_entry_text(text)


def object_view(item, identity, kind):
    result = {'id': identity, 'kind': kind, 'title': safe_text(item.get('title', item.get('name', '')))}
    for field in ('body', 'description', 'purpose', 'status', 'created_at', 'updated_at', 'due_date', 'start_date',
                  'expected_outcome', 'success_criteria', 'notes', 'board_date', 'end_date', 'category'):
        if isinstance(item.get(field), str):
            result[field] = safe_text(item[field])
    result['checklists'] = [
        {'title': safe_text(c.get('title')), 'items': [{'text': safe_text(i.get('text')), 'done': bool(i.get('done'))}
                                                    for i in c.get('items', [])]}
        for c in item.get('checklists', [])]
    if kind == 'plans':
        color = str(item.get('color', ''))
        result['color'] = color if re.fullmatch(r'#[0-9a-fA-F]{6}', color) else '#38bdf8'
    if kind == 'goals':
        result['milestones'] = [{'title': safe_text(m.get('title')), 'status': safe_text(m.get('status'))}
                                for m in item.get('milestones', [])]
    return result


def project(configuration, snapshot, documents, *, allow_secrets=False, secret_tags=(),
            enabled_reference_ids=None, disabled_reference_ids=None, context=None, matching_ids=None):
    from modules.hfl_corpus.secrets import is_secret_entry
    from modules.hfl_corpus.timeline import entry_evidence_id
    from modules.hfl_shares.scope import _entry_key
    controls = selection(configuration)
    if not set(controls.sections).intersection({'actions', 'ideas', 'boards', 'plans', 'graph'}):
        if 'entries' not in controls.sections:
            return replace(snapshot, entries=(), estimated_chars=0, sources=(), source_counts={}, tag_counts={},
                           available_references=0, enabled_reference_ids=(), earliest='', latest='')
        return replace(snapshot, activity={'sections': list(controls.sections), 'actions': [], 'ideas': [], 'boards': [], 'goals': [],
                                          'connections': {'nodes': [], 'edges': []}, 'graph': {'nodes': [], 'edges': []}})
    data = load_context() if context is None else context
    if configuration.include_secrets and not data.get('_secrets_supported', True):
        raise ValueError('The canonical API needs the workspace-sharing update before secret-backed actions and ideas can be included. Entries-only secret shares remain supported.')
    permitted, matching = set(), set()
    selected_entries = {e.id for e in snapshot.entries} if matching_ids is None else matching_ids
    for document in documents:
        for entry in document.entries:
            if is_secret_entry(entry, secret_tags or ('secrets',)) and not (allow_secrets and configuration.include_secrets):
                continue
            identity = _entry_key(document, entry.anchor, entry.text)
            for key in (identity, entry_evidence_id(entry.text)):
                permitted.add((document.relative_path, key))
                if identity in selected_entries:
                    matching.add((document.relative_path, key))
    excluded = set(controls.excluded_ids)
    workspaces = set(controls.workspace_ids)
    approved = controls.approved_ids

    def allowed(item):
        refs = [r for r in [item.get('source'), *item.get('evidence', [])] if isinstance(r, dict) and r.get('entry_id')]
        protected = item.get('secret') or set(item.get('tags', [])).intersection(secret_tags or ('secrets',))
        return (not protected or allow_secrets and configuration.include_secrets) and all(
            (r.get('path'), r['entry_id']) in permitted for r in refs)

    def in_workspace(item):
        if workspaces.intersection(item.get('workspace_ids', [])):
            return True
        refs = [r for r in [item.get('source'), *item.get('evidence', [])] if isinstance(r, dict)]
        if any((r.get('path'), r.get('entry_id')) in matching for r in refs):
            return True
        return not workspaces and not refs

    def chosen(identity, kind):
        return identity not in excluded and (approved is None or kind in controls.automatic or
                                            identity in approved.get(kind, []))

    pools, eligible, raw = {}, {}, {}
    for kind, prefix in [('actions', 'action:'), ('ideas', 'idea:'), ('plans', 'plan:')]:
        pools[kind], eligible[kind] = {}, set()
        for item in data.get(kind, []):
            identity = prefix + item['id']
            inactive = (kind == 'actions' and item.get('status') in {'done', 'completed', 'cancelled', 'dismissed', 'closed'}
                        and not controls.include_completed or kind == 'ideas' and item.get('status') == 'dismissed'
                        and not controls.include_dismissed)
            if not allowed(item) or inactive or identity in excluded:
                continue
            pools[kind][identity] = object_view(item, identity, kind)
            raw[identity] = item
            if in_workspace(item):
                eligible[kind].add(identity)

    objects = {k: [v for i, v in pools[k].items() if i in eligible[k] and chosen(i, k)]
               if k in controls.sections else [] for k in ('actions', 'ideas', 'plans')}
    published_entries = snapshot.entries if 'entries' in controls.sections else ()
    board_entry_ids = set()
    for board in data.get('maps', []) if 'boards' in controls.sections else []:
        if (not board.get('active', True) or not allowed(board) or not chosen('board:' + board['id'], 'boards') or
                workspaces and not workspaces.intersection(board.get('workspace_ids', []))):
            continue
        for member in board.get('members', []):
            if (not member.startswith('entry:') or member in excluded or member in board.get('hidden_members', []) or
                    approved is not None and 'boards' not in controls.automatic and member not in approved.get('members', [])):
                continue
            if member[6:] in selected_entries or board['id'] in controls.outside_board_ids:
                board_entry_ids.add(member[6:])
    if board_entry_ids:
        from modules.hfl_shares.scope import build_snapshot
        subset = tuple(replace(d, entries=tuple(e for e in d.entries if _entry_key(d, e.anchor, e.text) in board_entry_ids)) for d in documents)
        board_configuration = replace(configuration, activity={}, sources=('__all__',), tags=(), topic='',
                                      corpus_scope='', date_from='', date_to='', from_days=0)
        board_snapshot = build_snapshot(board_configuration, subset, allow_secrets=allow_secrets, secret_tags=secret_tags,
                                        enabled_reference_ids=enabled_reference_ids, disabled_reference_ids=disabled_reference_ids)
        published_entries = tuple({e.id: e for e in [*published_entries, *board_snapshot.entries]}.values())
        published_entries = tuple(replace(e, citation='S' + str(i + 1)) for i, e in enumerate(published_entries))
    entry_nodes = {'entry:' + e.id: {'id': 'entry:' + e.id, 'label': safe_text(e.moment or e.header), 'kind': 'entries', 'date': e.header[:19]} for e in published_entries}
    nodes = dict(entry_nodes)
    edges = []

    def add_object(obj):
        nodes[obj['id']] = {'id': obj['id'], 'label': obj['title'], 'kind': obj['kind'],
                            'body': obj.get('body', obj.get('description', '')),
                            'date': (obj.get('start_date', '') if obj['kind'] == 'plans' else obj.get('created_at', ''))[:10]}

    for rows in objects.values():
        for obj in rows:
            add_object(obj)
    # Derived entity nodes may only come from approved entry evidence. Do not
    # retain owner graph counts, locators, paths, hrefs or unrelated neighbors.
    if published_entries and ('graph' in controls.sections or objects['actions'] or objects['ideas'] or 'boards' in controls.sections):
        for row in mentions_for_documents(documents):
            origin = 'entry:' + row['id']
            if origin not in entry_nodes:
                continue
            for mention in row.get('mentions', []):
                if mention['id'] in excluded:
                    continue
                nodes[mention['id']] = {'id': mention['id'], 'label': safe_text(mention['label']), 'kind': mention['kind']}
                edges.append({'source': origin, 'target': mention['id'], 'relation': 'mentions'})
        for entry in published_entries:
            for kind, value in [('sources', entry.source), ('daily', entry.header[:10])]:
                target = kind + ':' + value
                if value and target not in excluded:
                    nodes[target] = {'id': target, 'label': safe_text(value), 'kind': kind}
                    edges.append({'source': 'entry:' + entry.id, 'target': target, 'relation': 'from-source' if kind == 'sources' else 'occurred-on'})

    boards, goals = [], {}
    from workflows.hfl.intent_reuse import list_graph
    # Only permission-checked owners may contribute linked checklist nodes.
    lists_snapshot = {**data,
                      'actions': [raw[i] for i in pools['actions']],
                      'ideas': [raw[i] for i in pools['ideas']]}
    list_nodes, list_edges = list_graph(lists_snapshot)
    available_lists = {n['id']: n for n in list_nodes}
    for board in data.get('maps', []) if 'boards' in controls.sections else []:
        identity = 'board:' + board['id']
        if (not board.get('active', True) or not allowed(board) or not chosen(identity, 'boards') or
                workspaces and not workspaces.intersection(board.get('workspace_ids', []))):
            continue
        view = object_view(board, identity, 'boards')
        raw[identity] = board
        add_object(view)
        local_nodes = {identity: nodes[identity]}
        local_edges = []
        for draft in board.get('drafts', []):
            draft_id = identity + ':' + draft['id']
            if draft_id in excluded:
                continue
            if approved is not None and 'boards' not in controls.automatic and draft_id not in approved.get('members', []):
                continue
            local_nodes[draft_id] = {'id': draft_id, 'label': safe_text(draft.get('title')), 'body': safe_text(draft.get('body')), 'kind': 'thoughts'}
        for member in board.get('members', []):
            if member in excluded or member in board.get('hidden_members', []):
                continue
            if approved is not None and 'boards' not in controls.automatic and member not in approved.get('members', []):
                continue
            for kind in ('actions', 'ideas'):
                if member in pools[kind] and (member in eligible[kind] or board['id'] in controls.outside_board_ids):
                    obj = pools[kind][member]
                    if not any(o['id'] == member for o in objects[kind]):
                        objects[kind].append(obj)
                    add_object(obj)
            if member in nodes:
                local_nodes[member] = nodes[member]
                local_edges.append({'source': identity, 'target': member, 'relation': 'contains'})
            if member in available_lists:
                list_node = available_lists[member]
                owner_prefix = 'action:' if list_node.get('owner_kind') == 'actionable' else 'idea:'
                owner_id = owner_prefix + list_node.get('owner_id', '')
                # Standalone lists are explicitly board-owned through membership.
                if (not list_node.get('owner_kind') or owner_id in nodes or
                        board['id'] in controls.outside_board_ids and owner_id in raw):
                    family = [n for n in list_nodes if n['id'] == member or n.get('list_id') == member]
                    for n in family:
                        if n['id'] in excluded or n['id'] in board.get('hidden_members', []):
                            continue
                        if approved is not None and 'boards' not in controls.automatic and n['id'] not in approved.get('members', []):
                            continue
                        local_nodes[n['id']] = {'id': n['id'], 'kind': n['kind'], 'label': safe_text(n['label']),
                                                'body': safe_text(n.get('body')), 'status': safe_text(n.get('status'))}
                    if member in local_nodes:
                        local_edges.append({'source': identity, 'target': member, 'relation': 'contains'})
        local_edges.extend({k: e[k] for k in ('source', 'target', 'relation')} for e in list_edges
                           if e['source'] in local_nodes and e['target'] in local_nodes)
        for edge in board.get('edges', []):
            a, b = [identity + ':' + edge[k] if edge[k].startswith('draft:') else edge[k] for k in ('source', 'target')]
            if a in local_nodes and b in local_nodes:
                local_edges.append({'source': a, 'target': b, 'relation': safe_text(edge.get('relation', 'related-to'))})
        goal = next((g for g in data.get('goals', []) if g['id'] == board.get('goal_id')), None)
        if (goal and allowed(goal) and 'goal:' + goal['id'] not in excluded and
                (approved is None or 'boards' in controls.automatic or 'goal:' + goal['id'] in approved.get('members', []))):
            goal_id = 'goal:' + goal['id']
            goals[goal_id] = object_view(goal, goal_id, 'goals')
            raw[goal_id] = goal
            add_object(goals[goal_id])
            local_nodes[goal_id] = nodes[goal_id]
            local_edges.append({'source': identity, 'target': goal_id, 'relation': 'supports'})
        positions = {}
        for key, value in board.get('positions', {}).items():
            key = identity + ':' + key if key.startswith('draft:') else key
            if key in local_nodes:
                positions[key] = {axis: float(value.get(axis, 0)) for axis in ('x', 'y')}
        sizes = {}
        for key, value in board.get('node_sizes', {}).items():
            key = identity + ':' + key if key.startswith('draft:') else key
            if key in local_nodes and isinstance(value, (int, float)) and 1 <= value <= 10:
                sizes[key] = value
        view['graph'] = {'nodes': list(local_nodes.values()), 'edges': local_edges, 'positions': positions, 'node_sizes': sizes}
        boards.append(view)
        nodes.update(local_nodes)
        edges.extend(local_edges)

    for obj in [*objects['actions'], *objects['ideas'], *objects['plans']]:
        item = raw[obj['id']]
        for ref in [item.get('source'), *item.get('evidence', [])]:
            if isinstance(ref, dict) and 'entry:' + str(ref.get('entry_id')) in nodes:
                edges.append({'source': obj['id'], 'target': 'entry:' + ref['entry_id'], 'relation': 'evidence'})
    edges.extend({'source': e['source'], 'target': e['target'], 'relation': safe_text(e.get('relation'))}
                 for e in data.get('links', []) if e['source'] in nodes and e['target'] in nodes)
    edges = list({(e['source'], e['target'], e['relation']): e for e in edges if e['source'] in nodes and e['target'] in nodes}.values())
    graph = {'nodes': list(nodes.values()), 'edges': edges}
    graph_view = controls.graph_view.model_dump()
    graph_view['positions'] = {key: value for key, value in graph_view['positions'].items() if key in nodes}
    payload = {**objects, 'sections': list(controls.sections), 'boards': boards, 'goals': list(goals.values()), 'connections': graph,
               'graph': {**graph, 'view': graph_view} if 'graph' in controls.sections else {'nodes': [], 'edges': []}}
    evidence = []
    disabled = set(configuration.disabled_reference_ids if disabled_reference_ids is None else disabled_reference_ids)
    enabled = None if enabled_reference_ids is None else set(enabled_reference_ids)
    shared_objects = [*objects['actions'], *objects['ideas'], *objects['plans'], *boards, *goals.values()]
    attachments = {}
    if configuration.references_enabled:
        from concurrent.futures import ThreadPoolExecutor
        from modules.hfl_shares.activity_references import references
        identities = [obj['id'] for obj in shared_objects if obj['kind'] in {'actions', 'ideas'}]
        def object_references(identity):
            item = raw.get(identity, {})
            if '_share_attachments' in item:
                return references(identity, manifests=item['_share_attachments'])
            return references(identity)
        with ThreadPoolExecutor(max_workers=8) as executor:
            attachments = dict(zip(identities, executor.map(object_references, identities)))
    for obj in shared_objects:
        identity = obj['id']
        citation = 'S' + str(1000000 + int(hashlib.sha256(identity.encode()).hexdigest()[:12], 16))
        refs = []
        for label, target in attachments.get(identity, []):
            rid = hashlib.sha256((identity + target).encode()).hexdigest()[:24]
            refs.append(SnapshotReference(rid, safe_text(label), 'activity_attachment', target,
                                         rid in enabled if enabled is not None else rid not in disabled))
        content = '\n'.join(str(raw.get(identity, {}).get(k, '')) for k in ('body', 'description', 'notes', 'purpose'))
        for url in sorted(set(re.findall(r'https://[^\s<>\)\]"\\]+', content))):
            if not configuration.references_enabled:
                break
            rid = hashlib.sha256((identity + url).encode()).hexdigest()[:24]
            refs.append(SnapshotReference(rid, url, 'external', url,
                                         rid in enabled if enabled is not None else rid not in disabled))
        lines = [obj['title']]
        lines.extend(f'{k.replace("_", " ")}: {v}' for k, v in obj.items() if k not in {'id', 'kind', 'title', 'graph', 'checklists', 'milestones'} and v)
        for checklist in obj.get('checklists', []):
            lines.append(checklist['title'])
            lines.extend(('- [x] ' if i['done'] else '- [ ] ') + i['text'] for i in checklist['items'])
        for milestone in obj.get('milestones', []):
            lines.append(milestone['title'] + ': ' + milestone['status'])
        if obj.get('graph'):
            lines.extend(n['label'] + ': ' + n.get('body', '') for n in obj['graph']['nodes'])
            labels = {n['id']: n['label'] for n in obj['graph']['nodes']}
            lines.extend(f'{labels[e["source"]]} — {e["relation"]} — {labels[e["target"]]}' for e in obj['graph']['edges'])
        evidence.append(SnapshotEntry(identity, citation, '', '', obj.get('updated_at', '')[:10], obj['title'],
                                      obj.get('body', obj.get('purpose', '')), obj['kind'], (), '\n\n'.join(lines), tuple(refs)))
    size = len(json.dumps(payload)) + sum(len(e.text) for e in [*published_entries, *evidence])
    if size > get_settings().hfl_share_max_snapshot_chars:
        raise ValueError('Selected activity exceeds the snapshot size limit. Narrow filters or deselect objects.')
    from collections import Counter
    return replace(snapshot, entries=published_entries, activity=payload, activity_entries=tuple(evidence), estimated_chars=size,
                   source_counts=dict(Counter(e.source for e in published_entries)),
                   tag_counts=dict(Counter(t for e in published_entries for t in e.tags)),
                   sources=tuple(sorted({e.source for e in published_entries})),
                   earliest=min((e.header[:10] for e in published_entries), default=''),
                   latest=max((e.header[:10] for e in published_entries), default=''),
                   available_references=sum(len(e.references) for e in [*published_entries, *evidence]),
                   enabled_reference_ids=tuple(r.id for e in [*published_entries, *evidence] for r in e.references if r.enabled))
