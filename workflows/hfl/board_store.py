"""Board-local planning and shared outcomes in the canonical intent database."""
import json
import uuid
from datetime import date
from workflows.hfl.colors import PIN_COLORS

from workflows.hfl.timeline_store import FollowUpConflict, isoformat


def text(value, label, limit, required=False):
    if not isinstance(value, str) or len(value) > limit or (required and not value.strip()):
        raise ValueError(f'Invalid {label}.')
    return value.strip()


def normalize_board(item):
    """Read old maps additively, preserving their IDs and revisions."""
    return {'purpose': item['name'], 'root': '', 'goal_id': '', 'drafts': [], 'edges': [],
            'created_at': '', 'updated_at': '', 'board_date': '', 'color': PIN_COLORS[0], 'node_sizes': {}, **item}


def validate_board(item):
    item.setdefault('color', PIN_COLORS[0])
    if item['color'] not in PIN_COLORS:
        raise ValueError('Choose a color from the Memory Signal palette.')
    item['purpose'] = text(item.get('purpose', item['name']), 'board purpose', 3000, True)
    drafts = item.setdefault('drafts', [])
    edges = item.setdefault('edges', [])
    if not isinstance(drafts, list) or len(drafts) > 500:
        raise ValueError('A board supports up to 500 draft thoughts.')
    ids = set(item.get('members', []))
    for draft in drafts:
        if not isinstance(draft, dict) or set(draft) - {'id', 'title', 'body'}:
            raise ValueError('Invalid draft thought.')
        identity = draft.get('id', '')
        if not isinstance(identity, str) or not identity.startswith('draft:') or len(identity) > 100 or identity in ids:
            raise ValueError('Draft IDs must be unique within the board.')
        ids.add(identity)
        text(draft.get('title'), 'thought title', 200, True)
        text(draft.get('body', ''), 'thought description', 60000)
    if not isinstance(edges, list) or len(edges) > 2000:
        raise ValueError('Invalid board connections.')
    for edge in edges:
        if not isinstance(edge, dict) or set(edge) - {'source', 'target', 'relation'}:
            raise ValueError('Invalid board connection.')
        if any(not isinstance(edge.get(k), str) for k in ('source', 'target')) or edge.get('source') not in ids or edge.get('target') not in ids or edge['source'] == edge['target']:
            raise ValueError('Connect two different members of this board.')
        if edge.get('relation', 'related-to') not in {'related-to', 'supports', 'alternative', 'depends-on'}:
            raise ValueError('Invalid board relationship.')
    if not isinstance(item.get('root', ''), str) or (item.get('root', '') and item['root'] not in ids):
        raise ValueError('The starting object must belong to the board.')
    goal = item.get('goal_id', '')
    if not isinstance(goal, str) or (goal and 'goal:' + goal not in ids):
        raise ValueError('The primary goal must belong to the board.')
    sizes = item.setdefault('node_sizes', {})
    if not isinstance(sizes, dict) or len(sizes) > 10500 or any(
        not isinstance(key, str) or type(value) is not int or not 1 <= value <= 10
        for key, value in sizes.items()
    ):
        raise ValueError('Orb sizes must be whole numbers from 1 to 10.')
    item['node_sizes'] = {key: value for key, value in sizes.items() if key in ids}
    return ids


class BoardStoreMixin:
    def promoted_idea(self, identity, draft_id):
        with self.followups.connect() as db:
            row = db.execute('SELECT idea_id FROM board_promotions WHERE board_id=? AND draft_id=?', (identity, draft_id)).fetchone()
        return row['idea_id'] if row else None

    def promote_connection(self, identity, edge, version):
        with self.followups.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            row = db.execute('SELECT payload FROM idea_maps WHERE id=?', (identity,)).fetchone()
            if not row:
                raise KeyError(identity)
            board = normalize_board(json.loads(row['payload']))
            values = (edge['source'], edge['target'], edge.get('relation', 'related-to'))
            if edge not in board['edges']:
                if db.execute('SELECT 1 FROM idea_links WHERE source=? AND target=? AND relation=?', values).fetchone():
                    return board
                raise FollowUpConflict('This connection is no longer on the board.')
            if board['version'] != version:
                raise FollowUpConflict('The board changed. Reload before promoting.')
            db.execute('INSERT OR IGNORE INTO idea_links VALUES (?,?,?,?)', (*values, isoformat()))
            board['edges'].remove(edge)
            board['version'] += 1
            board['updated_at'] = isoformat()
            db.execute('UPDATE idea_maps SET version=?,payload=? WHERE id=?', (board['version'], json.dumps(board), identity))
        return board

    def goals(self):
        with self.followups.connect() as db:
            return [{'color': PIN_COLORS[0], **json.loads(row['payload'])} for row in db.execute('SELECT g.payload FROM intent_goals g LEFT JOIN goal_order o ON o.id=g.id ORDER BY COALESCE(o.position,2147483647),g.rowid')]

    def goal(self, identity):
        with self.followups.connect() as db:
            row = db.execute('SELECT payload FROM intent_goals WHERE id=?', (identity,)).fetchone()
        if row is None:
            raise KeyError(identity)
        return {'color': PIN_COLORS[0], **json.loads(row['payload'])}

    def reorder_goals(self, identities):
        if not isinstance(identities, list) or any(not isinstance(i, str) for i in identities) or len(set(identities)) != len(identities):
            raise ValueError('Choose a valid Goal order.')
        with self.followups.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            if set(identities) != {r['id'] for r in db.execute('SELECT id FROM intent_goals')}:
                raise FollowUpConflict('Goals changed. Reload before reordering.')
            db.execute('DELETE FROM goal_order')
            db.executemany('INSERT INTO goal_order VALUES (?,?)', [(identity, index) for index, identity in enumerate(identities)])

    def save_goal(self, raw, actor, identity=None):
        allowed = {'title', 'body', 'success_criteria', 'status', 'target_date', 'progress_notes', 'milestones', 'linked_objects', 'version', 'request_id', 'color'}
        if set(raw) - allowed:
            raise ValueError('Unsupported goal fields.')
        previous = self.goal(identity) if identity else {}
        item = {**previous, **raw}
        item.setdefault('color', PIN_COLORS[0])
        if item['color'] not in PIN_COLORS:
            raise ValueError('Choose a color from the Memory Signal palette.')
        for key, limit in [('title', 200), ('body', 60000), ('success_criteria', 6000), ('progress_notes', 20000)]:
            item[key] = text(item.get(key, ''), key.replace('_', ' '), limit, key == 'title')
        item.setdefault('status', 'proposed')
        if item['status'] not in {'proposed', 'active', 'paused', 'achieved', 'dropped'}:
            raise ValueError('Invalid goal status.')
        item.setdefault('target_date', '')
        text(item['target_date'], 'target date', 10)
        if item['target_date']:
            date.fromisoformat(item['target_date'])
        milestones = item.setdefault('milestones', [])
        links = item.setdefault('linked_objects', [])
        if not isinstance(links, list) or len(links) > 500 or any(not isinstance(i, str) or not i.startswith(('idea:', 'action:')) for i in links):
            raise ValueError('Link Goals to existing Ideas or Actions.')
        if not isinstance(milestones, list) or len(milestones) > 100:
            raise ValueError('Use up to 100 milestones.')
        seen = set()
        for milestone in milestones:
            if not isinstance(milestone, dict) or set(milestone) - {'id', 'title', 'status', 'target_date', 'actions'}:
                raise ValueError('Invalid milestone.')
            mid = text(milestone.get('id'), 'milestone ID', 100, True)
            if mid in seen:
                raise ValueError('Milestone IDs must be unique.')
            seen.add(mid)
            text(milestone.get('title'), 'milestone title', 300, True)
            if milestone.get('status', 'planned') not in {'planned', 'active', 'achieved', 'dropped'}:
                raise ValueError('Invalid milestone status.')
            if milestone.get('target_date'):
                text(milestone['target_date'], 'milestone date', 10)
                date.fromisoformat(milestone['target_date'])
            actions = milestone.get('actions', [])
            if not isinstance(actions, list) or len(actions) > 100 or any(not isinstance(a, str) for a in actions):
                raise ValueError('Invalid milestone actions.')
        identity = identity or 'goal-' + str(uuid.UUID(raw['request_id']))
        item.pop('request_id', None)
        item.update(id=identity, version=previous.get('version', 0) + 1, created_at=previous.get('created_at', isoformat()), updated_at=isoformat())
        with self.followups.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            found = db.execute('SELECT * FROM intent_goals WHERE id=?', (identity,)).fetchone()
            if not previous and found:
                existing = json.loads(found['payload'])
                if any(existing.get(k) != v for k, v in raw.items() if k != 'request_id'):
                    raise FollowUpConflict('This goal creation request was already used.')
                return existing
            if previous and (not found or found['version'] != raw.get('version')):
                raise FollowUpConflict('The goal changed. Reopen it before saving.')
            encoded = json.dumps(item)
            db.execute('INSERT INTO intent_goals VALUES (?,?,?) ON CONFLICT(id) DO UPDATE SET version=excluded.version,payload=excluded.payload', (identity, item['version'], encoded))
            db.execute('INSERT INTO goal_history VALUES (?,?,?,?)', (identity, item['version'], str(actor), encoded))
            from workflows.hfl.board_memory import record_memory
            record_memory(db, item, previous, kind='goal', revision=item['version'], timestamp=item['updated_at'])
        return item

    def delete_board(self, identity, version):
        with self.followups.connect() as db:
            if not db.execute('DELETE FROM idea_maps WHERE id=? AND version=?', (identity, version)).rowcount:
                raise FollowUpConflict('The board changed. Reload before deleting.')

    def promote_draft(self, identity, draft_id, version, actor):
        """Create a shared idea and replace the local reference in one transaction.

        Board edges stay local: promotion does not assert tentative relationships.
        """
        with self.followups.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            row = db.execute('SELECT payload FROM idea_maps WHERE id=?', (identity,)).fetchone()
            if not row:
                raise KeyError(identity)
            board = normalize_board(json.loads(row['payload']))
            shared_id = 'idea-' + str(uuid.uuid5(uuid.NAMESPACE_URL, identity + ':' + draft_id))
            shared_node = 'idea:' + shared_id
            draft = next((d for d in board['drafts'] if d['id'] == draft_id), None)
            receipt = db.execute('SELECT idea_id FROM board_promotions WHERE board_id=? AND draft_id=?', (identity, draft_id)).fetchone()
            if receipt:
                if draft:
                    raise FollowUpConflict('This thought was already promoted. Create a new thought or edit the shared Idea.')
                return {'board': board, 'idea_id': receipt['idea_id']}
            if not draft and shared_node in board['members']:
                return {'board': board, 'idea_id': shared_id}
            if board['version'] != version:
                raise FollowUpConflict('The board changed. Reload before promoting.')
            if not draft:
                raise KeyError(draft_id)
            idea = dict(id=shared_id, title=draft['title'], body=draft.get('body', ''), description='', checklists=[], status='suggested', origin='board', version=1, created_at=isoformat(), updated_at=isoformat())
            encoded = json.dumps(idea)
            db.execute('INSERT INTO idea_edits VALUES (?,?,?)', (shared_id, 1, encoded))
            db.execute('INSERT INTO idea_history VALUES (?,?,?,?)', (shared_id, 1, str(actor), encoded))
            db.execute('INSERT INTO board_promotions VALUES (?,?,?)', (identity, draft_id, shared_id))
            board['drafts'] = [d for d in board['drafts'] if d['id'] != draft_id]
            board['members'] = list(dict.fromkeys([*board['members'], shared_node]))
            if board['root'] == draft_id:
                board['root'] = shared_node
            if draft_id in board.get('positions', {}):
                board['positions'][shared_node] = board['positions'].pop(draft_id)
            if draft_id in board['node_sizes']:
                board['node_sizes'][shared_node] = board['node_sizes'].pop(draft_id)
            for edge in board['edges']:
                for end in ('source', 'target'):
                    if edge[end] == draft_id:
                        edge[end] = shared_node
            board['version'] += 1
            board['updated_at'] = isoformat()
            db.execute('UPDATE idea_maps SET version=?,payload=? WHERE id=?', (board['version'], json.dumps(board), identity))
        return {'board': board, 'idea_id': shared_id}
