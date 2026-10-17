"""Opt-in response budget for the main activity graph; other consumers are unchanged."""

MIN_NODES = 1000
DEFAULT_NODES = 1000
DEFAULT_EDGES = 2000
MAX_NODES = 10000
MAX_EDGES = 5000


def bounded_graph(source, since, until, query, shared, context, node_limit, edge_limit, preview):
    from modules.hfl_corpus import entities

    # Preserve canonical filtering and authorization before counting or sampling.
    graph = entities.graph(source, since, until, 0, query, shared, context)
    nodes, edges = graph['nodes'], graph['edges']
    exceeded = len(nodes) > node_limit or len(edges) > edge_limit
    capacity = dict(exceeded=exceeded, preview=bool(exceeded and preview),
                    total_nodes=len(nodes), total_edges=len(edges),
                    node_limit=node_limit, edge_limit=edge_limit)
    if exceeded:
        if preview:
            # Stable recency order, independent of the current viewport/preset.
            ranked = sorted(nodes, key=lambda n: (n.get('date', ''), n['id']), reverse=True)
            neighbors = {}
            for edge in edges:
                neighbors.setdefault(edge['source'], []).append(edge['target'])
                neighbors.setdefault(edge['target'], []).append(edge['source'])
            ids = set()
            for node in ranked:
                for identity in (node['id'], *neighbors.get(node['id'], [])):
                    if len(ids) >= node_limit:
                        break
                    ids.add(identity)
                if len(ids) >= node_limit:
                    break
            nodes = [n for n in ranked if n['id'] in ids]
            edges = [e for e in edges if e['source'] in ids and e['target'] in ids][:edge_limit]
        else:
            nodes, edges = [], []
    return {**graph, 'nodes': nodes, 'edges': edges, 'total_nodes': capacity['total_nodes'],
            'limit': node_limit, 'truncated': exceeded, 'capacity': capacity}
