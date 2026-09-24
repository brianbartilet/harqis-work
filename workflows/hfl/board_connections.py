"""Atomic, revision-checked board and shared connection commands."""
import json
import uuid

from workflows.hfl.timeline_store import FollowUpConflict, isoformat


RELATIONS = {'related-to', 'supports', 'alternative', 'depends-on', 'develops-into', 'source-date', 'context'}


def connection_key(edge):
    return json.dumps([edge['source'], edge['target'], edge.get('relation', 'related-to')], separators=(',', ':'))


def validate_connection(edge):
    if not isinstance(edge, dict) or any(not isinstance(edge.get(k), str) or not edge[k] for k in ('source', 'target')):
        raise ValueError('Choose two connected objects.')
    if edge['source'] == edge['target'] or edge.get('relation', 'related-to') not in RELATIONS:
        raise ValueError('Choose two different objects and a supported relationship.')
    if edge.get('direction', 'forward') not in ('forward', 'both', 'none'):
        raise ValueError('Choose one-way, bidirectional, or no arrow.')


class ConnectionStoreMixin:
    def edit_connection(self, identity, raw):
        from workflows.hfl.board_store import normalize_board, validate_board
        operation, scope = raw.get('operation'), raw.get('scope', 'local')
        if operation not in ('create', 'update', 'remove', 'width') or scope not in ('local', 'shared'):
            raise ValueError('Choose a supported connection operation.')
        old = raw.get('edge')
        validate_connection(old)
        new = raw.get('replacement', old)
        validate_connection(new)
        old_key, new_key = connection_key(old), connection_key(new)
        with self.followups.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            row = db.execute('SELECT payload FROM idea_maps WHERE id=?', (identity,)).fetchone()
            if not row:
                raise KeyError(identity)
            board = normalize_board(json.loads(row['payload']))
            if board['version'] != raw.get('version'):
                raise FollowUpConflict('The board changed. Refresh before retrying.')
            from workflows.hfl.intent_reuse import list_graph
            list_nodes, _ = list_graph(self.snapshot()) if any(i.startswith('list:') for i in board['members']) else ([], [])
            extra_ids = {n['id'] for n in list_nodes if n.get('list_id') in board['members']} - set(board.get('hidden_members', []))
            members = set(board['members']) | {d['id'] for d in board['drafts']} | extra_ids
            if any(e[k] not in members for e in (old, new) for k in ('source', 'target')):
                raise ValueError('Connect members of this board.')
            local = next((e for e in board['edges'] if connection_key(e) == old_key), None)
            values = tuple(json.loads(old_key))
            shared = db.execute("SELECT l.*, COALESCE(m.direction,'forward') AS direction, COALESCE(m.revision,l.created_at) AS revision FROM idea_links l LEFT JOIN idea_link_metadata m USING(source,target,relation) WHERE l.source=? AND l.target=? AND l.relation=?", values).fetchone()
            if operation in ('create', 'update'):
                candidate = old if operation == 'create' else new
                reverse_key = connection_key(dict(source=candidate['target'], target=candidate['source'], relation=candidate.get('relation', 'related-to')))
                if reverse_key != old_key:
                    reverse_local = any(connection_key(e) == reverse_key for e in board['edges'])
                    reverse_shared = db.execute('SELECT 1 FROM idea_links WHERE source=? AND target=? AND relation=?', tuple(json.loads(reverse_key))).fetchone()
                    if reverse_local or reverse_shared:
                        raise ValueError('A connection already exists in the opposite direction. Edit its arrows instead.')
            if operation == 'create':
                if scope != 'local' or local or shared:
                    raise ValueError('This connection already exists or cannot be created here.')
                board['edges'].append({k: old.get(k, 'related-to' if k == 'relation' else 'forward') for k in ('source', 'target', 'relation', 'direction')})
            else:
                if (scope == 'local' and not local) or (scope == 'shared' and not shared):
                    raise FollowUpConflict('This connection changed or was removed. Refresh before retrying.')
                if scope == 'shared' and old.get('relation') in {'develops-into', 'source-date', 'context'}:
                    raise ValueError('Automatically generated connections are read-only.')
                if scope == 'shared' and shared['revision'] != raw.get('revision'):
                    raise FollowUpConflict('The shared connection changed. Refresh before retrying.')
                if operation == 'width':
                    width = raw.get('width')
                    if type(width) is not int or not 1 <= width <= 5:
                        raise ValueError('Connection sizes must be whole numbers from 1 to 5.')
                    board['edge_widths'][old_key] = width
                else:
                    if operation == 'update' and new_key != old_key:
                        duplicate = any(connection_key(e) == new_key for e in board['edges']) or db.execute('SELECT 1 FROM idea_links WHERE source=? AND target=? AND relation=?', tuple(json.loads(new_key))).fetchone()
                        if duplicate:
                            raise ValueError('That connection already exists.')
                    if scope == 'local':
                        board['edges'].remove(local)
                        if operation == 'update':
                            board['edges'].append({k: new.get(k, 'related-to' if k == 'relation' else 'forward') for k in ('source', 'target', 'relation', 'direction')})
                    else:
                        db.execute('DELETE FROM idea_links WHERE source=? AND target=? AND relation=?', values)
                        db.execute('DELETE FROM idea_link_metadata WHERE source=? AND target=? AND relation=?', values)
                        if operation == 'update':
                            new_values = tuple(json.loads(new_key))
                            db.execute('INSERT INTO idea_links VALUES (?,?,?,?)', (*new_values, shared['created_at']))
                            db.execute('INSERT INTO idea_link_metadata VALUES (?,?,?,?,?)', (*new_values, new.get('direction', 'forward'), str(uuid.uuid4())))
                        # Keep each board's presentation attached to the renamed link.
                        for other in db.execute('SELECT id,payload FROM idea_maps WHERE id != ?', (identity,)).fetchall():
                            item = normalize_board(json.loads(other['payload']))
                            if old_key in item['edge_widths']:
                                width = item['edge_widths'].pop(old_key)
                                if operation == 'update':
                                    item['edge_widths'][new_key] = width
                                item['version'] += 1
                                item['updated_at'] = isoformat()
                                db.execute('UPDATE idea_maps SET version=?,payload=? WHERE id=?', (item['version'], json.dumps(item), other['id']))
                    width = board['edge_widths'].pop(old_key, None)
                    if operation == 'update' and width is not None:
                        board['edge_widths'][new_key] = width
            validate_board(board, extra_ids)
            board['version'] += 1
            board['updated_at'] = isoformat()
            db.execute('UPDATE idea_maps SET version=?,payload=? WHERE id=?', (board['version'], json.dumps(board), identity))
        return board
