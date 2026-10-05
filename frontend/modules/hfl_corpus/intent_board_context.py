"""Complete, permission-filtered board context for intent processing."""


def context():
    from modules.hfl_corpus.ideas_api import canonical_snapshot
    from modules.hfl_corpus.entities import graph, current_entries
    snapshot = canonical_snapshot()
    boards = [b for b in snapshot['maps'] if b.get('active', True)]
    if not boards:
        return []
    projection = graph(limit=0)
    nodes = {n['id']: n for n in projection['nodes']}
    for entry in current_entries():
        identity = 'entry:' + entry['id']
        if identity in nodes:
            nodes[identity] = {**nodes[identity], 'body': entry.get('text', '')}
    # Keep full intent content (not only the graph's display labels).
    for collection, prefix in [('ideas', 'idea:'), ('actions', 'action:'), ('goals', 'goal:')]:
        for item in snapshot.get(collection, []):
            identity = prefix + item['id']
            if identity in nodes:
                nodes[identity] = {**item, **nodes[identity]}
    result = []
    for board in sorted(boards, key=lambda b: (b.get('updated_at', ''), b['id']), reverse=True):
        members = set(board.get('members', []))
        members.update(n['id'] for n in nodes.values() if n.get('list_id') in members
                       and n['id'] not in board.get('hidden_members', []))
        available = members & nodes.keys()
        local = {d['id'] for d in board.get('drafts', [])}
        allowed = available | local
        result.append({**{k: board.get(k, '') for k in ('id', 'name', 'purpose', 'prompt', 'goal_id', 'updated_at')},
                       'members': [nodes[i] for i in sorted(available)], 'drafts': board.get('drafts', []),
                       'connections': [e for e in [*projection['edges'], *board.get('edges', [])]
                                       if e['source'] in allowed and e['target'] in allowed]})
    return result
