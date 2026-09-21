"""Join canonical intent records to the permitted corpus graph."""
from workflows.hfl.ideas_store import local_day


def extend(base, snapshot, *, since='', until='', query='', sources=None, context='', shared=False, limit=100):
    nodes = {n['id']: n for n in base['nodes']}
    edges = list(base['edges'])
    corpus_ids = set(nodes)
    sources = {sources} if isinstance(sources, str) and sources else set(sources or [])
    # Follow explicit chains from scoped corpus anchors, including idea → idea.
    adjacent, linked_days = {}, {}
    goal_links = [dict(source=target, target='goal:' + goal['id'], relation='supports')
                  for goal in snapshot.get('goals', [])
                  for target in set(goal.get('linked_objects', []) + [a for m in goal.get('milestones', []) for a in m.get('actions', [])])]
    boards = [{**b, 'title': b['name'], 'body': b.get('purpose', ''), 'status': 'board',
               'source_date': b.get('board_date', '')} for b in snapshot.get('maps', [])]
    snapshot = {**snapshot, 'boards': boards}
    for memory in snapshot.get('memories', []):
        entry_id = memory.get('graph_entry_id', '')
        if entry_id not in corpus_ids:
            continue
        # Drafts remain board-local; their recall entries connect to their owning board.
        target = 'board:' + memory['board_id'] if memory['board_id'] else memory['object_id']
        goal_links.extend([dict(source=target, target=entry_id, relation='memory-entry'),
                           dict(source=target, target='daily:' + memory['day'], relation='memory-date')])
    goal_links += [dict(source='board:' + b['id'], target=target, relation=relation)
                   for b in boards for target, relation in
                   [*([('daily:' + b['board_date'], 'board-date')] if b.get('board_date') else []),
                    *([('goal:' + b['goal_id'], 'supports')] if b.get('goal_id') else [])]]
    for edge in [*snapshot['links'], *goal_links]:
        adjacent.setdefault(edge['source'], set()).add(edge['target'])
        adjacent.setdefault(edge['target'], set()).add(edge['source'])
        for a, b in [(edge['source'], edge['target']), (edge['target'], edge['source'])]:
            if b.startswith('daily:'):
                linked_days.setdefault(a, set()).add(b[6:])
    for collection, prefix in [('ideas', 'idea:'), ('actions', 'action:')]:
        for item in snapshot.get(collection, []):
            source = item.get('source') or {}
            if source.get('entry_id'):
                a, b = prefix + item['id'], item.get('graph_source_id') or 'entry:' + source['entry_id']
                adjacent.setdefault(a, set()).add(b)
                adjacent.setdefault(b, set()).add(a)
    reachable, queue = set(corpus_ids), list(corpus_ids)
    for identity in queue:
        for neighbor in adjacent.get(identity, ()):
            if neighbor not in reachable:
                reachable.add(neighbor)
                queue.append(neighbor)
    for topic in snapshot['topics']:
        nodes.setdefault(topic['id'], dict(id=topic['id'], label=topic['label'], kind='topics'))
    for collection, prefix, kind in [('ideas', 'idea:', 'ideas'), ('actions', 'action:', 'actions'), ('goals', 'goal:', 'goals'), ('boards', 'board:', 'boards')]:
        for item in snapshot.get(collection, []):
            source = item.get('source') or {}
            source_entry = item.get('graph_source_id') or 'entry:' + source.get('entry_id', '')
            if context and prefix + item['id'] not in reachable:
                continue
            if sources and prefix + item['id'] not in reachable and 'manual-entry' not in sources:
                continue
            created = local_day(item['created_at']) if item.get('created_at') else ''
            dates = {d for d in [created, source.get('date', '')[:10], item.get('source_date', '')] if d}
            if collection == 'boards':
                dates = {item.get('board_date') or created} - {''}
            dates.update(ref.get('date', '')[:10] for ref in item.get('evidence', []) if isinstance(ref, dict) and ref.get('date'))
            linked_dates = linked_days.get(prefix + item['id'], set())
            if (since or until) and not any((not since or d >= since) and (not until or d <= until) for d in dates | linked_dates):
                continue
            identity = prefix + item['id']
            nodes[identity] = dict(id=identity, object_id=item['id'], label=item['title'], kind=kind, status=item['status'], date=created,
                                   description=item.get('description', ''), body=item.get('body', ''), checklists=item.get('checklists', []), version=item.get('version', 0))
            if collection == 'goals':
                nodes[identity]['success_criteria'] = item.get('success_criteria', '')
            if collection == 'boards':
                nodes[identity].update(date=item.get('board_date') or created,
                                       created_at=item.get('created_at', ''), updated_at=item.get('updated_at', ''),
                                       board_date=item.get('board_date', ''))
            for day in dates:
                target = 'daily:' + day
                nodes.setdefault(target, dict(id=target, label=day, kind='daily'))
                if collection == 'boards':
                    edges.append(dict(source=identity, target=target, relation='board-date', method='intent-metadata', evidence=day))
                    continue
                if day == created:
                    edges.append(dict(source=identity, target=target, relation='created-on', method='intent-metadata', evidence=day))
                if day != created or day == source.get('date', '')[:10] or day == item.get('source_date'):
                    edges.append(dict(source=identity, target=target, relation='source-date', method='intent-metadata', evidence=day))
            if source_entry in corpus_ids:
                edges.append(dict(source=identity, target=source_entry, relation='source-entry', evidence='', method='intent-metadata'))
            for evidence_id in item.get('graph_evidence_ids', []):
                if evidence_id in corpus_ids:
                    edges.append(dict(source=identity, target=evidence_id, relation='evidence', evidence='', method='intent-metadata'))
            if collection == 'ideas' and item.get('followup_id'):
                edges.append(dict(source=identity, target='action:' + item['followup_id'], relation='develops-into', evidence='', method='intent-metadata'))
    for edge in [*snapshot['links'], *goal_links]:
        for identity in (edge['source'], edge['target']):
            other = edge['target'] if identity == edge['source'] else edge['source']
            if identity.startswith('daily:') and other in nodes:
                nodes.setdefault(identity, dict(id=identity, label=identity[6:], kind='daily'))
        derived = edge in goal_links
        edges.append({**edge, 'manual': not derived, 'evidence': '', 'method': 'goal' if derived else 'owner'})
    if context or sources or since or until:
        connected = {identity for edge in edges if edge['source'] in nodes and edge['target'] in nodes for identity in (edge['source'], edge['target'])}
        manual_topics = {topic['id'] for topic in snapshot['topics']} - corpus_ids
        nodes = {k: v for k, v in nodes.items() if k not in manual_topics or k in connected}
    edges = [e for e in edges if e['source'] in nodes and e['target'] in nodes]
    if query:
        matches = {n['id'] for n in nodes.values() if query.casefold() in (n['label'] + ' ' + n.get('description', '') + ' ' + n.get('body', '')).casefold()}
        visible = matches | {e['target'] if e['source'] in matches else e['source'] for e in edges if e['source'] in matches or e['target'] in matches}
        nodes = {k: v for k, v in nodes.items() if k in visible}
    if shared:
        from collections import Counter
        counts = Counter(i for e in edges for i in (e['source'], e['target']))
        nodes = {k: v for k, v in nodes.items() if v['kind'] == 'entries' or counts[k] > 1}
    total = len(nodes)
    if limit and total > limit:
        # Recent intents and their dates participate in the same detail budget.
        ranked = sorted(nodes.values(), key=lambda n: (n.get('date', n['label'] if n['kind'] == 'daily' else ''), n['id']), reverse=True)
        selected = {n['id'] for n in ranked[:limit]}
        nodes = {k: v for k, v in nodes.items() if k in selected}
    unique = {(e['source'], e['target'], e['relation']): e for e in edges if e['source'] in nodes and e['target'] in nodes}
    return {**base, 'nodes': list(nodes.values()), 'edges': list(unique.values()), 'total_nodes': total, 'limit': limit, 'truncated': total > len(nodes)}
