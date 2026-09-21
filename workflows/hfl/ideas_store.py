"""Ideas and relationships share the canonical follow-up database.

Generated suggestions retain their IDs. Owner edits live in an overlay so a
generation refresh cannot overwrite them. Maps own membership, never objects.
"""
import json
import math
import uuid
from datetime import datetime, date
from zoneinfo import ZoneInfo

from workflows.hfl.timeline_store import FollowUpConflict, isoformat


from workflows.hfl.object_content import content_fields, migrate_content, consolidated_description


from workflows.hfl.board_store import BoardStoreMixin, normalize_board, validate_board


class IdeasStore(BoardStoreMixin):
    def __init__(self, followups):
        self.followups = followups
        self.path = followups.path
        with followups.connect() as db:
            db.executescript('''
                CREATE TABLE IF NOT EXISTS idea_edits (id TEXT PRIMARY KEY, version INTEGER NOT NULL, payload TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS idea_history (id TEXT NOT NULL, version INTEGER NOT NULL, actor TEXT NOT NULL, payload TEXT NOT NULL, PRIMARY KEY(id,version));
                CREATE TABLE IF NOT EXISTS idea_topics (id TEXT PRIMARY KEY, label TEXT NOT NULL, created_at TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS idea_links (source TEXT NOT NULL, target TEXT NOT NULL, relation TEXT NOT NULL, created_at TEXT NOT NULL, PRIMARY KEY(source,target,relation));
                CREATE TABLE IF NOT EXISTS intent_goals (id TEXT PRIMARY KEY, version INTEGER NOT NULL, payload TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS goal_history (id TEXT NOT NULL, version INTEGER NOT NULL, actor TEXT NOT NULL, payload TEXT NOT NULL, PRIMARY KEY(id,version));
                CREATE TABLE IF NOT EXISTS board_promotions (board_id TEXT NOT NULL, draft_id TEXT NOT NULL, idea_id TEXT NOT NULL, PRIMARY KEY(board_id,draft_id));
                CREATE TABLE IF NOT EXISTS board_memories (event_id TEXT PRIMARY KEY, entry_id TEXT NOT NULL, object_id TEXT NOT NULL, board_id TEXT NOT NULL, day TEXT NOT NULL, payload TEXT NOT NULL, staged INTEGER NOT NULL DEFAULT 0);
                CREATE TABLE IF NOT EXISTS goal_order (id TEXT PRIMARY KEY, position INTEGER NOT NULL);
                CREATE TABLE IF NOT EXISTS board_order (id TEXT PRIMARY KEY, position INTEGER NOT NULL);
                CREATE TABLE IF NOT EXISTS idea_maps (id TEXT PRIMARY KEY, version INTEGER NOT NULL, payload TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS idea_item_actions (idea_id TEXT NOT NULL, checklist_id TEXT NOT NULL, item_id TEXT NOT NULL, action_id TEXT NOT NULL, PRIMARY KEY(idea_id,checklist_id,item_id,action_id));
                CREATE TABLE IF NOT EXISTS idea_conversions (request_id TEXT PRIMARY KEY, fingerprint TEXT NOT NULL);
            ''')
            migrate_content(db, 'idea_edits')

    def ideas(self):
        with self.followups.connect() as db:
            rows = db.execute('SELECT * FROM timeline_suggestions').fetchall()
            edits = {r['id']: json.loads(r['payload']) for r in db.execute('SELECT * FROM idea_edits')}
        result = {}
        for row in rows:
            item = json.loads(row['payload'])
            item.update(id=row['id'], status=row['status'], followup_id=row['followup_id'])
            item.setdefault('created_at', row['updated_at'])
            item.setdefault('updated_at', row['updated_at'])
            item.setdefault('version', 0)
            item.setdefault('description', item.get('recommendation', ''))
            item.setdefault('body', '')
            item.setdefault('checklists', [])
            result[row['id']] = item
        for identity, edit in edits.items():
            generated = result.get(identity, {})
            result[identity] = {**generated, **edit}
            if generated:
                result[identity].update(status=generated['status'], followup_id=generated.get('followup_id', ''))
        with self.followups.connect() as db:
            links = [dict(r) for r in db.execute('SELECT * FROM idea_item_actions')]
        for item in result.values():
            item['body'] = consolidated_description(item)
            item['description'] = ''
            item['item_actions'] = [r for r in links if r['idea_id'] == item['id']]
            for checklist in item.get('checklists', []):
                checklist.setdefault('cover', False)
        return list(result.values())

    def idea(self, identity):
        item = next((i for i in self.ideas() if i['id'] == identity), None)
        if item is None:
            raise KeyError(identity)
        return item

    def save_idea(self, raw, actor, identity=None):
        allowed = {'title', 'description', 'body', 'checklists', 'status', 'source', 'expected_outcome', 'matrix', 'matrix_confidence', 'matrix_reason', 'version', 'request_id', 'source_date'}
        if set(raw) - allowed:
            raise ValueError('Unsupported idea fields.')
        previous = self.idea(identity) if identity else {}
        item = {**previous, **raw}
        if not isinstance(item.get('title'), str) or not item['title'].strip() or len(item['title']) > 200:
            raise ValueError('An idea needs a title of at most 200 characters.')
        item.update(content_fields(item))
        from workflows.hfl.timeline_store import validate_matrix
        item.update(validate_matrix(item))
        if not isinstance(item.get('expected_outcome', ''), str) or len(item.get('expected_outcome', '')) > 3000:
            raise ValueError('Expected outcome must be text of at most 3000 characters.')
        if item.get('status', 'suggested') not in {'suggested', 'adopted', 'dismissed'}:
            raise ValueError('Unknown idea status.')
        if item.get('source_date'):
            from datetime import date
            date.fromisoformat(item['source_date'])
        if not identity:
            identity = 'idea-' + str(uuid.UUID(raw['request_id']))
        item.update(id=identity, title=item['title'].strip(), version=previous.get('version', 0) + 1,
                    created_at=previous.get('created_at', isoformat()), updated_at=isoformat(),
                    status=item.get('status', 'suggested'), origin=previous.get('origin', 'manual' if not previous else 'generated'))
        item.pop('request_id', None)
        with self.followups.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            found = db.execute('SELECT * FROM idea_edits WHERE id=?', (identity,)).fetchone()
            if not previous and found:
                existing = json.loads(found['payload'])
                if any(existing.get(k) != item.get(k) for k in raw if k != 'request_id'):
                    raise FollowUpConflict('This creation request was already used.')
                return existing
            if previous and (raw.get('version') != previous['version'] or (found and found['version'] != raw['version'])):
                raise FollowUpConflict('The idea changed. Reopen it before saving.')
            encoded = json.dumps(item)
            db.execute('INSERT INTO idea_edits VALUES (?,?,?) ON CONFLICT(id) DO UPDATE SET version=excluded.version,payload=excluded.payload', (identity, item['version'], encoded))
            db.execute('INSERT INTO idea_history VALUES (?,?,?,?)', (identity, item['version'], str(actor), encoded))
            db.execute('UPDATE timeline_suggestions SET status=? WHERE id=?', (item['status'], identity))
        return item

    def topic(self, label):
        from workflows.hfl.entity_store import digest
        if not isinstance(label, str) or not label.strip() or len(label) > 120:
            raise ValueError('Use a topic name of at most 120 characters.')
        label = ' '.join(label.split())
        identity = 'entity:' + digest(['topics', label])[:24]
        with self.followups.connect() as db:
            db.execute('INSERT OR IGNORE INTO idea_topics VALUES (?,?,?)', (identity, label, isoformat()))
        return {'id': identity, 'kind': 'topics', 'label': label}

    def links(self):
        with self.followups.connect() as db:
            return [dict(row) for row in db.execute('SELECT * FROM idea_links')]

    def link(self, source, target, relation='related-to', remove=False):
        if source == target or relation not in {'related-to', 'develops-into', 'source-date', 'context', 'supports', 'depends-on', 'alternative'}:
            raise ValueError('Choose two different objects and a supported relationship.')
        with self.followups.connect() as db:
            if remove:
                db.execute('DELETE FROM idea_links WHERE source=? AND target=? AND relation=?', (source, target, relation))
            else:
                db.execute('INSERT OR IGNORE INTO idea_links VALUES (?,?,?,?)', (source, target, relation, isoformat()))

    def maps(self):
        with self.followups.connect() as db:
            return [normalize_board(json.loads(row['payload'])) for row in db.execute('SELECT m.* FROM idea_maps m LEFT JOIN board_order o ON o.id=m.id ORDER BY COALESCE(o.position,2147483647),m.rowid')]

    def map(self, identity):
        with self.followups.connect() as db:
            row = db.execute('SELECT payload FROM idea_maps WHERE id=?', (identity,)).fetchone()
        if row is None:
            raise KeyError(identity)
        return normalize_board(json.loads(row['payload']))

    def reorder_boards(self, identities):
        if not isinstance(identities, list) or any(not isinstance(i, str) for i in identities) or len(set(identities)) != len(identities):
            raise ValueError('Choose a valid board order.')
        with self.followups.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            if set(identities) != {r['id'] for r in db.execute('SELECT id FROM idea_maps')}:
                raise FollowUpConflict('Boards changed. Reload before reordering.')
            db.execute('DELETE FROM board_order')
            db.executemany('INSERT INTO board_order VALUES (?,?)', [(identity, index) for index, identity in enumerate(identities)])

    def save_map(self, raw, identity=None):
        if set(raw) - {'name', 'members', 'positions', 'version', 'request_id', 'prompt', 'purpose', 'root', 'goal_id', 'drafts', 'edges', 'board_date', 'color'}:
            raise ValueError('Unsupported mind-map fields.')
        previous = self.map(identity) if identity else {}
        item = {**previous, **raw}
        now = isoformat()
        item['created_at'] = previous.get('created_at', '') if previous else now
        item['updated_at'] = now
        item['board_date'] = item.get('board_date') or local_day(item['created_at'] or now)
        if not isinstance(item['board_date'], str) or len(item['board_date']) != 10:
            raise ValueError('Use a valid board date.')
        date.fromisoformat(item['board_date'])
        if not isinstance(item.get('name'), str) or not item['name'].strip() or len(item['name']) > 100:
            raise ValueError('A map needs a name of at most 100 characters.')
        members = item.get('members', [])
        if not isinstance(members, list) or len(members) > 10000 or any(not isinstance(i, str) or len(i) > 200 for i in members):
            raise ValueError('Invalid map membership.')
        board_ids = validate_board(item)
        positions = item.get('positions', {})
        if not isinstance(positions, dict) or len(positions) > 10000:
            raise ValueError('Invalid map positions.')
        for key, point in positions.items():
            if key not in board_ids or not isinstance(point, dict) or any(type(point.get(v)) not in (int, float) or not math.isfinite(point[v]) or abs(point[v]) > 1e7 for v in ('x', 'y')):
                raise ValueError('Invalid map position.')
        prompt = item.get('prompt', '')
        if not isinstance(prompt, str) or len(prompt) > 20000:
            raise ValueError('Brainstorming instructions are too long.')
        item.update(id=identity or 'map-' + str(uuid.UUID(raw['request_id'])), version=previous.get('version', 0) + 1,
                    members=list(dict.fromkeys(members)), positions=positions, prompt=prompt)
        item.pop('request_id', None)
        with self.followups.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            found = db.execute('SELECT * FROM idea_maps WHERE id=?', (item['id'],)).fetchone()
            if previous and (not found or found['version'] != raw.get('version')):
                raise FollowUpConflict('The map changed. Reload before saving.')
            if not previous and found:
                existing = normalize_board(json.loads(found['payload']))
                if any(existing.get(k) != v for k, v in raw.items() if k != 'request_id'):
                    raise FollowUpConflict('This board creation request was already used.')
                return existing
            db.execute('INSERT INTO idea_maps VALUES (?,?,?) ON CONFLICT(id) DO UPDATE SET version=excluded.version,payload=excluded.payload', (item['id'], item['version'], json.dumps(item)))
            from workflows.hfl.board_memory import record_memory
            old_drafts = {d['id']: d for d in previous.get('drafts', [])}
            for draft in item['drafts']:
                record_memory(db, draft, old_drafts.get(draft['id'], {}), kind='thought',
                              revision=item['version'], timestamp=now, board=item)
        return normalize_board(item)

    def snapshot(self):
        with self.followups.connect() as db:
            topics = [dict(row) for row in db.execute('SELECT * FROM idea_topics')]
            memories = [dict(row) for row in db.execute('SELECT entry_id,object_id,board_id,day FROM board_memories')]
        return {'ideas': self.ideas(), 'actions': self.followups.list() + self.followups.list(closed=True), 'topics': topics, 'links': self.links(), 'maps': self.maps(), 'goals': self.goals(), 'memories': memories}


def local_day(timestamp):
    return datetime.fromisoformat(timestamp).astimezone(ZoneInfo('Asia/Singapore')).date().isoformat()
