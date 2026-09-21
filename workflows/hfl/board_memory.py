"""Transactional thought/Goal memories, delivered by the existing HFL outbox job."""
import json
import logging
from datetime import datetime
from urllib.parse import urlencode
from zoneinfo import ZoneInfo

THOUGHT_FIELDS = ('title', 'body')
GOAL_FIELDS = ('title', 'body', 'success_criteria', 'status', 'target_date',
               'progress_notes', 'milestones', 'linked_objects')


def record_memory(db, item, previous, *, kind, revision, timestamp, board=None):
    """Record the immutable envelope in the owner's transaction; no network I/O."""
    fields = THOUGHT_FIELDS if kind == 'thought' else GOAL_FIELDS
    changed = [key for key in fields if item.get(key, '') != previous.get(key, '')]
    if previous and not changed:
        return
    from workflows.hfl.dto import HflEntry
    from workflows.hfl.persistence import make_envelope

    node = item['id'] if kind == 'thought' else 'goal:' + item['id']
    scope = board['id'] if board else ''
    event = f'{kind}:{scope}:{node}:{revision}'
    params = {'select': node}
    if board:
        params['board'] = board['id']
    url = '/hfl-corpus/graph?' + urlencode(params)
    action = 'Updated' if previous else 'Created'
    parts = [f'{action} {kind}: {item["title"]}', item.get('body', '')]
    if board:
        parts.append(f'Board: {board["name"]}\nBoard purpose: {board["purpose"]}')
    if kind == 'goal':
        for key in GOAL_FIELDS[2:]:
            value = item.get(key)
            if value:
                parts.append(f'{key.replace("_", " ").capitalize()}: ' +
                             (json.dumps(value, ensure_ascii=False) if isinstance(value, list) else str(value)))
    if previous:
        parts.append('Changed fields: ' + ', '.join(changed))
    # Include revision in content too: a later return to the same wording is a new memory.
    parts.append(f'Object: {node}\nMemory key: {scope + "/" if scope else ""}{node}\nRevision: {revision}')
    when = datetime.fromisoformat(timestamp).astimezone(ZoneInfo('Asia/Singapore')).replace(tzinfo=None)
    entry = HflEntry(when=when, moment=f'{kind.capitalize()} {action.lower()}: {item["title"]}',
                     what_happened='\n\n'.join(p for p in parts if p),
                     tags=(kind, 'board-memory', action.lower()),
                     references=(f'[Open {kind}]({url})',))
    envelope = make_envelope(entry, source='manual-entry', dedup_key=event)
    db.execute('INSERT INTO board_memories(event_id,entry_id,object_id,board_id,day,payload) VALUES (?,?,?,?,?,?)',
               (event, envelope.entry.entry_id, node, scope, when.date().isoformat(),
                json.dumps(envelope.to_payload())))


def stage_pending_memories(store=None, *, limit=100):
    """Hand off to the durable file outbox before acknowledging each DB event."""
    from workflows.hfl.persistence import EntryEnvelope, save_to_outbox
    if store is None:
        from workflows.hfl.timeline_store import FollowUpStore, store_path
        from workflows.hfl.ideas_store import IdeasStore
        path = store_path()
        if not path.exists():
            return 0
        store = IdeasStore(FollowUpStore(path))
    staged = 0
    with store.followups.connect() as db:
        # Serialize concurrent drains so a late handoff cannot resurrect a delivered file.
        db.execute('BEGIN IMMEDIATE')
        rows = db.execute('SELECT event_id,payload FROM board_memories WHERE staged=0 ORDER BY rowid LIMIT ?',
                          (max(1, int(limit)),)).fetchall()
        for row in rows:
            try:
                save_to_outbox(EntryEnvelope.from_payload(json.loads(row['payload'])))
            except Exception:
                logging.getLogger(__name__).exception('Board memory remains pending: %s', row['event_id'])
                continue
            db.execute('UPDATE board_memories SET staged=1 WHERE event_id=?', (row['event_id'],))
            staged += 1
    return staged
