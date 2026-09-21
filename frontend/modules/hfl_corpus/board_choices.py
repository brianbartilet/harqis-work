"""Permission-filtered board choices without building the corpus edge graph."""
from datetime import datetime, timezone
from urllib.parse import quote


def stamp(value):
    try:
        parsed = datetime.fromisoformat(value.replace('Z', '+00:00'))
        return parsed.replace(tzinfo=parsed.tzinfo or timezone.utc).astimezone(timezone.utc).isoformat()
    except (TypeError, ValueError, AttributeError):
        return ''


def catalogue():
    from modules.hfl_corpus import entities, ideas_api, ideas_graph
    from modules.hfl_corpus.entity_source import entry_locator
    from workflows.hfl.entity_store import get_store
    rows = entities.projection()
    profiles = get_store().profiles()
    nodes = {}

    def add(node, updated):
        identity = node['id']
        previous = nodes.get(identity, {})
        nodes[identity] = {**node, 'updated_at': max(previous.get('updated_at', ''), stamp(updated))}

    for entry in rows:
        updated = entry.get('updated_at') or entry['date']
        add(dict(id='entry:' + entry['id'], label=entry['title'], kind='entries',
                 date=entry['date'], source=entry['source'], tags=entry.get('tags', []),
                 locator=entry_locator(entry), href='/hfl-corpus/entities/entry/' + quote(entry['id'], safe='')), updated)
        for mention in entry['mentions']:
            profile = profiles.get(mention['id'], {})
            add({**{k: mention[k] for k in ('id', 'label', 'kind', 'resolution') if k in mention},
                 'label': profile.get('name') or mention['label'], 'categories': profile.get('categories', [])},
                max(stamp(updated), stamp(profile.get('updated'))))
        for kind, value in [('sources', entry['source']), ('daily', entry['date'][:10])]:
            if value:
                add(dict(id=kind + ':' + value, label=value, kind=kind), updated)
    # Reuse intent projection and its permission checks, using the same corpus read.
    snapshot = ideas_api.permitted_snapshot(entries=rows)
    result = ideas_graph.extend({'nodes': list(nodes.values()), 'edges': []}, snapshot, limit=0)
    updates = {prefix + item['id']: item.get('updated_at') or item.get('created_at', '')
               for collection, prefix in [('ideas', 'idea:'), ('actions', 'action:'), ('goals', 'goal:'), ('maps', 'board:')]
               for item in snapshot.get(collection, [])}
    return {n['id']: {**n, 'updated_at': stamp(updates.get(n['id']) or n.get('updated_at')
                     or profiles.get(n['id'], {}).get('updated') or n.get('date')
                     or (n['label'] if n['kind'] == 'daily' else ''))}
            for n in result['nodes']}
