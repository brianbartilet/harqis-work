"""Read-only action neighborhood, including board-local relationships."""
from fastapi import HTTPException


def project(action_id, shared, boards):
    root = 'action:' + action_id
    nodes = {n['id']: {**n, 'boards': []} for n in shared['nodes']}
    if root not in nodes:
        raise HTTPException(404, 'Action unavailable or protected.')
    edges = [{**e, 'scope': 'shared'} for e in shared['edges']]
    for board in boards:
        provenance = {'id': board['id'], 'name': board['name']}
        members = set(board['members'])
        for identity in members & nodes.keys():
            nodes[identity]['boards'].append(provenance)
        if root not in members:
            continue
        # Draft IDs are only unique inside their board.
        drafts = {d['id']: {**d, 'id': f"board:{board['id']}:{d['id']}",
                            'label': d['title'], 'kind': 'drafts', 'boards': [provenance]}
                  for d in board.get('drafts', [])}
        for edge in board.get('edges', []):
            if root not in (edge['source'], edge['target']):
                continue
            resolved = {}
            for side in ('source', 'target'):
                identity = edge[side]
                if identity in drafts:
                    node = drafts[identity]
                    nodes[node['id']] = node
                    resolved[side] = node['id']
                elif identity in members and identity in nodes:
                    resolved[side] = identity
            if len(resolved) == 2:
                edges.append({**edge, **resolved, 'scope': 'board', 'board': provenance})
    valid = [e for e in edges if e['source'] in nodes and e['target'] in nodes]
    neighbors = {root}
    for edge in valid:
        if root in (edge['source'], edge['target']):
            neighbors.update((edge['source'], edge['target']))
    return {'root': root, 'nodes': [n for identity, n in nodes.items() if identity in neighbors],
            'edges': [e for e in valid if e['source'] in neighbors and e['target'] in neighbors]}


def connected_actions(shared, boards):
    """Return visible actions with at least one shared or board-local edge."""
    nodes = {node['id'] for node in shared['nodes']}
    dates = {node['id'] for node in shared['nodes'] if node.get('kind') == 'daily'}
    connected = set()
    for edge in shared['edges']:
        endpoints = {edge['source'], edge['target']}
        if endpoints <= nodes and not endpoints & dates:
            connected.update(endpoints)
    for board in boards:
        members = set(board['members']) & nodes
        drafts = {draft['id'] for draft in board.get('drafts', [])}
        for edge in board.get('edges', []):
            endpoints = {edge['source'], edge['target']}
            if endpoints <= members | drafts:
                connected.update(endpoints & members)
    return sorted(identity.removeprefix('action:') for identity in connected if identity.startswith('action:'))
