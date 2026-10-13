"""Idea/action board associations, projected from canonical board membership."""
import json


def prepend_action(db, identity):
    """Persist insertion before all existing cards, including manually ordered ones."""
    position = db.execute('SELECT COALESCE(MIN(position), 0) - 1 FROM followup_board_order').fetchone()[0]
    db.execute('INSERT OR REPLACE INTO followup_board_order VALUES (?,?)', (identity, position))


def replace_idea(db, idea_id, action_id):
    """Replace a promoted idea on every board without losing local connections."""
    from workflows.hfl.timeline_store import isoformat
    source, target = 'idea:' + idea_id, 'action:' + action_id
    for board in boards(db):
        if source not in board.get('members', []):
            continue
        board['members'] = list(dict.fromkeys(target if node == source else node for node in board['members']))
        for edge in board.get('edges', []):
            for key in ('source', 'target'):
                if edge[key] == source:
                    edge[key] = target
        board['edges'] = [edge for edge in board.get('edges', []) if edge['source'] != edge['target']]
        for key in ('positions', 'node_sizes'):
            if source in board.get(key, {}):
                board[key][target] = board[key].pop(source)
        widths = {}
        for key, width in board.get('edge_widths', {}).items():
            parts = json.loads(key)
            parts[:2] = [target if node == source else node for node in parts[:2]]
            if parts[0] != parts[1]:
                widths[json.dumps(parts, separators=(',', ':'))] = width
        board['edge_widths'] = widths
        if board.get('root') == source:
            board['root'] = target
        board.update(version=board['version'] + 1, updated_at=isoformat())
        db.execute('UPDATE idea_maps SET version=?,payload=? WHERE id=?',
                   (board['version'], json.dumps(board), board['id']))


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
    origins = {}
    if prefix == 'action:' and db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='idea_links'").fetchone():
        for row in db.execute("SELECT source,target FROM idea_links WHERE relation='develops-into' AND source LIKE 'idea:%' AND target LIKE 'action:%'"):
            origins.setdefault(row['target'][7:], set()).add(row['source'][5:])
    result = []
    for item in items:
        value = {**item, 'board_ids': sorted(b['id'] for b in available if prefix + item['id'] in b.get('members', []))}
        if prefix == 'action:':
            source_ids = origins.get(item['id'], set()).copy()
            if item.get('suggestion_id'):
                source_ids.add(item['suggestion_id'])
            value['origin_idea_ids'] = sorted(source_ids)
        result.append(value)
    return result


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
