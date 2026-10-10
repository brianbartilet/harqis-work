"""Read-only navigation derived exclusively from a grant's published snapshot."""
from collections import defaultdict


def guest_views(grant):
    activity = grant.snapshot.activity
    sections = activity.get('sections')
    if sections is None:
        # Old generated shares retain their publication-time scope, never the
        # owner's mutable recipe. Frozen legacy snapshots can infer from data.
        config = grant.live_configuration
        sections = (config.activity or {}).get('sections') if config else None
    if sections is None:
        sections = [key for key in ('actions', 'ideas', 'plans', 'boards', 'graph') if activity.get(key)]
    sections = set(sections)
    objects = {kind: activity.get(kind, []) if kind in sections else []
               for kind in ('actions', 'ideas', 'plans', 'boards')}
    menu = [('entries', 'Activity entries')]
    if objects['actions'] or objects['ideas']:
        menu.append(('actions', 'Actions and ideas'))
    if objects['plans']:
        menu.append(('plans', 'Plans'))
    if objects['boards']:
        menu.append(('boards', 'Idea boards'))
    if 'graph' in sections and activity.get('graph', {}).get('nodes'):
        menu.append(('graph', 'Activity graph'))

    evidence = {entry.id: entry for entry in grant.snapshot.activity_entries}
    destinations = {}
    for kind in ('actions', 'ideas', 'plans', 'boards'):
        view = 'actions' if kind == 'ideas' else kind
        for obj in objects[kind]:
            if obj['id'] in evidence:
                destinations[obj['id']] = view
    # Board-only members and mapped goals remain inspectable even when the
    # standalone actions/ideas navigation is disabled.
    board_evidence = []
    if objects['boards']:
        for entry in grant.snapshot.activity_entries:
            if entry.id not in destinations or destinations[entry.id] == 'boards':
                destinations[entry.id] = 'boards'
                board_evidence.append(entry)
    categories = defaultdict(list)
    for obj in objects['plans']:
        categories[obj.get('category') or 'Uncategorized'].append(obj)
    date_key = lambda obj: (obj.get('end_date') or obj.get('start_date') or '', obj.get('start_date') or '', obj['id'])
    groups = [(name, sorted(dates, key=date_key, reverse=True)) for name, dates in categories.items()]
    groups.sort(key=lambda group: group[0].casefold())
    groups.sort(key=lambda group: date_key(group[1][0])[0], reverse=True)
    board_targets = {}
    for index, board in enumerate(objects['boards']):
        for node in board.get('graph', {}).get('nodes', []):
            if node['id'] in evidence:
                board_targets.setdefault(evidence[node['id']].citation[1:], {'board': index, 'node': node['id']})
    return {
        'share_menu': menu,
        'shared_objects': objects,
        'shared_plan_groups': groups,
        'board_evidence': board_evidence,
        'activity_evidence': evidence,
        'board_evidence_targets': board_targets,
        'evidence_destinations': {
            **{entry.citation[1:]: destinations.get(entry.id, 'entries') for entry in grant.snapshot.activity_entries},
        },
    }
