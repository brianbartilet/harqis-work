"""Idea/action board associations, projected from canonical board membership."""
import json


def board_ids(value):
    if not isinstance(value, list) or len(value) > 10000 or any(
        not isinstance(identity, str) or not identity or len(identity) > 200 for identity in value
    ):
        raise ValueError('Choose valid board IDs.')
    return sorted(set(value))


def boards(db):
    if not db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='idea_maps'").fetchone():
        return []
    return [json.loads(row['payload']) for row in db.execute('SELECT payload FROM idea_maps')]


def memberships(db, node):
    return sorted(b['id'] for b in boards(db) if node in b.get('members', []))


def project(db, items, prefix):
    available = boards(db)
    return [{**item, 'board_ids': sorted(b['id'] for b in available if prefix + item['id'] in b.get('members', []))}
            for item in items]


def associate(db, node, proposed):
    """LLM selections only add currently active, existing boards."""
    active = {b['id'] for b in boards(db) if b.get('active', True)}
    return sync(db, node, sorted(set(memberships(db, node)) | (set(board_ids(proposed)) & active)))


def sync(db, node, selected):
    """Update only membership and dependent layout inside the caller's transaction.

    Existing inactive associations are retained. New attachments are orphan orbs:
    no object-to-object connections are manufactured.
    """
    from workflows.hfl.timeline_store import isoformat
    selected = set(board_ids(selected))
    available = {b['id']: b for b in boards(db)}
    if selected - available.keys():
        raise ValueError('A selected board was removed. Reload before saving.')
    for identity in selected:
        board = available[identity]
        if not board.get('active', True) and node not in board.get('members', []):
            raise ValueError('Inactive boards cannot receive new objects.')
    for identity, board in available.items():
        attached = node in board.get('members', [])
        wanted = identity in selected or (attached and not board.get('active', True))
        if attached == wanted:
            continue
        board['members'] = [*board.get('members', []), node] if wanted else [i for i in board['members'] if i != node]
        if wanted and len(board['members']) > 10000:
            raise ValueError('A board supports up to 10000 members.')
        if not wanted:
            board['edges'] = [e for e in board.get('edges', []) if node not in (e['source'], e['target'])]
            for key in ('positions', 'node_sizes'):
                board.get(key, {}).pop(node, None)
            board['edge_widths'] = {k: v for k, v in board.get('edge_widths', {}).items() if node not in json.loads(k)[:2]}
            if board.get('root') == node:
                board['root'] = ''
        board.update(version=board['version'] + 1, updated_at=isoformat())
        db.execute('UPDATE idea_maps SET version=?,payload=? WHERE id=?',
                   (board['version'], json.dumps(board), identity))
    return memberships(db, node)
