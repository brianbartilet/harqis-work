"""Owner checklist notes with optimistic saves and a transactional lifecycle outbox."""
import json
import logging
from datetime import datetime, timezone
from typing import Literal
from uuid import uuid4

import bleach
from fastapi import APIRouter, BackgroundTasks, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field, model_validator

from auth import get_current_user
from modules.hfl_corpus.graph_views import connection
from modules.hfl_corpus.router import _workspace_authorize
from modules.hfl_corpus import workspace_views
from services.markdown import render_markdown

router = APIRouter(prefix='/hfl-corpus/quick-notes')
log = logging.getLogger(__name__)


class Item(BaseModel):
    """Ordered checklist row. Children immediately follow their top-level parent."""
    model_config = ConfigDict(extra='forbid')
    id: str = Field(min_length=1, max_length=80)
    text: str = Field(default='', max_length=4000)
    completed: bool = False
    parent: str | None = Field(default=None, max_length=80, description='Parent item ID, or null for a top-level item. Only one nesting level is supported.')


class Reference(BaseModel):
    """Link to an existing action (actionable) or idea; source records are unchanged."""
    kind: Literal['actionable', 'idea']
    id: str = Field(min_length=1, max_length=160)


class Note(BaseModel):
    """Complete writable note state, not a patch. Omitted fields reset to defaults."""
    model_config = ConfigDict(extra='forbid')
    title: str = Field(default='', max_length=200)
    items: list[Item] = Field(default_factory=list, max_length=200)
    workspace_ids: list[str] = Field(default_factory=list, max_length=100, description='Linked Space IDs. Empty means visible in every Space context; does not change the main page context.')
    references: list[Reference] = Field(default_factory=list, max_length=50)
    color: Literal['slate', 'blue', 'mint', 'plum', 'amber'] = 'slate'
    pinned: bool = False
    archived: bool = False
    order: float = Field(default=0, allow_inf_nan=False, description='Ascending order within pinned and unpinned groups. Ties sort by note ID.')
    revision: int = Field(default=0, ge=0, description='0 for a new identity; the latest returned revision for update or deletion. Successful writes increment it.')

    @model_validator(mode='after')
    def valid_tree(self):
        seen = set()
        current_parent = None
        for item in self.items:
            if item.id in seen:
                raise ValueError('Checklist item IDs must be unique.')
            if item.parent and item.parent != current_parent:
                raise ValueError('Children must follow their parent; only one nesting level is supported.')
            if item.parent is None:
                current_parent = item.id
            seen.add(item.id)
        self.workspace_ids = list(dict.fromkeys(self.workspace_ids))
        return self


class ItemResponse(Item):
    html: str = Field(description='Sanitized display HTML, including bold, italics and hyperlinks. Read-only; omit from writes.')


class NoteResponse(Note):
    id: str = Field(description='Client-selected identity from the request path. Read-only in the body.')
    updated_at: str = Field(description='Server-generated UTC ISO 8601 timestamp. Read-only.')
    items: list[ItemResponse]


class NotesResponse(BaseModel):
    notes: list[NoteResponse]
    active: list[str] = Field(description='Active Space IDs from shared page context. Empty means All activity.')


AUTH_RESPONSES = {401: {'description': 'Owner session required.'}}
WRITE_RESPONSES = {
    **AUTH_RESPONSES,
    403: {'description': 'Missing or invalid X-CSRF-Token. Refresh the signed-in page.'},
    409: {'description': 'Stale revision, missing identity with a nonzero revision, or previously deleted note. Reload before retrying.'},
}
NOTE_EXAMPLE = {
    'title': 'Travel checklist',
    'items': [
        {'id': 'documents', 'text': '**Documents**', 'completed': False, 'parent': None},
        {'id': 'passport', 'text': 'Passport', 'completed': False, 'parent': 'documents'},
    ],
    'workspace_ids': [], 'references': [], 'color': 'blue', 'pinned': True,
    'archived': False, 'order': 0, 'revision': 0,
}
NOTE_BODY = {'requestBody': {'content': {'application/json': {'examples': {
    'create': {'summary': 'Create at a new client-selected identity', 'value': NOTE_EXAMPLE},
    'archive': {'summary': 'Archive using the current revision (replace 1)', 'value': {**NOTE_EXAMPLE, 'archived': True, 'revision': 1}},
    'restore': {'summary': 'Restore using the current revision (replace 2)', 'value': {**NOTE_EXAMPLE, 'revision': 2}},
}}}}}


def schema(db):
    db.execute('CREATE TABLE IF NOT EXISTS quick_notes (owner TEXT NOT NULL, id TEXT NOT NULL, payload TEXT NOT NULL, revision INTEGER NOT NULL, updated TEXT NOT NULL, deleted INTEGER NOT NULL DEFAULT 0, PRIMARY KEY(owner,id))')
    db.execute('CREATE TABLE IF NOT EXISTS quick_note_events (id TEXT PRIMARY KEY, owner TEXT NOT NULL, payload TEXT NOT NULL, delivered INTEGER NOT NULL DEFAULT 0)')


def decode(row):
    return {**json.loads(row['payload']), 'id': row['id'], 'revision': row['revision'], 'updated_at': row['updated']}


def presentation(note):
    return {**note, 'items': [{**i, 'html': bleach.clean(str(render_markdown(i['text'])), tags=['strong', 'em', 'a', 'p', 'br'], attributes={'a': ['href', 'target', 'rel']}, protocols=['https', 'http', 'mailto'], strip=True)} for i in note['items']]}


def space_context():
    return workspace_views.listing()


def listing(owner):
    context = space_context()
    active = [v['id'] if isinstance(v, dict) else v for v in context['active']]
    with connection() as db:
        schema(db)
        notes = [decode(r) for r in db.execute('SELECT * FROM quick_notes WHERE owner=? AND deleted=0', (owner,))]
    notes = [n for n in notes if not active or not n['workspace_ids'] or set(active).intersection(n['workspace_ids'])]
    notes.sort(key=lambda n: (not n['pinned'], n['order'], n['id']))
    return {'notes': [presentation(n) for n in notes], 'active': active}


def save(owner, identity, note, delete=False):
    now = datetime.now(timezone.utc).isoformat()
    with connection() as db:
        schema(db)
        db.execute('BEGIN IMMEDIATE')
        row = db.execute('SELECT * FROM quick_notes WHERE owner=? AND id=?', (owner, identity)).fetchone()
        if row and (row['deleted'] or row['revision'] != note.revision) or not row and note.revision:
            raise HTTPException(409, 'This note changed in another window. Your edits are retained; reload the latest note before retrying.')
        if delete and not row:
            raise HTTPException(404, 'Note not found.')
        before = decode(row) if row else None
        payload = note.model_dump(exclude={'revision'})
        revision = note.revision + 1
        db.execute('INSERT INTO quick_notes VALUES (?,?,?,?,?,?) ON CONFLICT(owner,id) DO UPDATE SET payload=excluded.payload,revision=excluded.revision,updated=excluded.updated,deleted=excluded.deleted',
                   (owner, identity, json.dumps(payload), revision, now, int(delete)))
        operation = 'deleted' if delete else 'created' if not before else 'archived' if note.archived and not before['archived'] else None
        if operation:
            event = {'operation': operation, 'note': {**payload, 'id': identity}, 'when': now}
            db.execute('INSERT INTO quick_note_events VALUES (?,?,?,0)', (uuid4().hex, owner, json.dumps(event)))
    return presentation({**payload, 'id': identity, 'revision': revision, 'updated_at': now})


def deliver_events(owner):
    """Retry safely; the canonical outbox and deterministic key prevent duplicates."""
    with connection() as db:
        schema(db)
        rows = db.execute('SELECT * FROM quick_note_events WHERE owner=? AND delivered=0 LIMIT 20', (owner,)).fetchall()
    for row in rows:
        try:
            from workflows.hfl.dto import HflEntry
            from workflows.hfl.persistence import submit_hfl_entry
            event = json.loads(row['payload'])
            note = event['note']
            body = '\n'.join(('  ' if i['parent'] else '') + '- [' + ('x' if i['completed'] else ' ') + '] ' + i['text'] for i in note['items'])
            entry = HflEntry(when=datetime.fromisoformat(event['when']), moment=f"Quick Notes {event['operation']}: {note['title'] or 'Untitled checklist'}", what_happened=body or 'Empty checklist', tags=('quick-notes', event['operation']), references=(f"Quick Note: {note['id']}",))
            submit_hfl_entry(entry, source='quick-notes', dedup_key=row['id'])
            with connection() as db:
                db.execute('UPDATE quick_note_events SET delivered=1 WHERE id=?', (row['id'],))
        except Exception:
            log.warning('Quick Notes lifecycle delivery pending', exc_info=False)


@router.get('', summary='List Quick Notes in the shared Space context',
            responses={**AUTH_RESPONSES, 200: {'model': NotesResponse}})
def read(request: Request, background_tasks: BackgroundTasks):
    """Return the owner's non-deleted notes, including archived notes.

    Uses shared main-page Space context; this route has no Space-selection query
    parameter. Unlinked notes always match; linked notes match any active Space.
    With no active Spaces, all notes match. Sorts pinned first, then ascending
    `order`, then ID. Clients separate active/archive views using `archived`.
    Reading also retries pending lifecycle delivery in the background.

    These dashboard routes use the owner session, not the standalone Corpus
    bearer token. Data lives in this host's configured profile database.
    """
    _workspace_authorize(request)
    owner = get_current_user(request)
    background_tasks.add_task(deliver_events, owner)
    return listing(owner)


@router.put('/{identity}', summary='Create or replace a Quick Note',
            responses={**WRITE_RESPONSES, 200: {'model': NoteResponse}}, openapi_extra=NOTE_BODY)
def write(identity: str, note: Note, request: Request, background_tasks: BackgroundTasks):
    """Send complete writable state with the owner session and `X-CSRF-Token`.

    Choose a new identity of at most 80 characters (a UUID is recommended) and
    revision 0 to create. Updates require the latest revision. This is replacement,
    not PATCH: include every field you want to retain. Omit response-only `id`,
    `updated_at` and item `html` from the body. Both create and update return 200.

    Set `archived=true` to archive or false to restore. Set `pinned`, `color`,
    `order`, Space IDs and references in the same payload. Item IDs must be unique;
    each child's parent must be the immediately preceding top-level group.
    Clients perform parent/child completion cascades and reorder entire subtrees;
    the API stores and validates the submitted final state.

    Creation and transitions into archive enqueue a corpus lifecycle snapshot.
    Ordinary edits and restore do not. Saving succeeds independently of corpus
    delivery, which uses a durable outbox and retries on subsequent reads/writes.
    """
    _workspace_authorize(request, write=True)
    if len(identity) > 80 or not identity:
        raise HTTPException(422, 'Invalid note ID.')
    owner = get_current_user(request)
    result = save(owner, identity, note)
    background_tasks.add_task(deliver_events, owner)
    return result


@router.delete('/{identity}', summary='Delete a Quick Note',
               responses={**WRITE_RESPONSES, 404: {'description': 'Unknown identity with revision 0.'},
                          200: {'model': NoteResponse}},
               openapi_extra={'requestBody': {'content': {'application/json': {'example': {**NOTE_EXAMPLE, 'revision': 1}}}}})
def remove(identity: str, note: Note, request: Request, background_tasks: BackgroundTasks):
    """Requires a JSON body containing the current complete writable note and revision.

    Uses the owner session and `X-CSRF-Token`. The frontend asks for confirmation;
    API callers must obtain any needed confirmation themselves. Returns the final
    note snapshot with an incremented revision (200, not 204), removes it from
    listings, and enqueues a deletion snapshot for the Activity Corpus. Deletion
    does not erase earlier corpus snapshots. The identity cannot be recreated;
    repeating deletion returns 409. Use archive instead for reversible removal.
    """
    _workspace_authorize(request, write=True)
    owner = get_current_user(request)
    result = save(owner, identity, note, delete=True)
    background_tasks.add_task(deliver_events, owner)
    return result
