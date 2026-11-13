"""Agents presentation layout; only widget Space membership is shared."""
import json
import uuid

from fastapi import HTTPException
from pydantic import Field
from modules.hfl_corpus.graph_views import connection
from modules.hfl_corpus import workspace_views
from modules.second_brain import hud


class Layout(hud.Layout):
    shared_revision: int = Field(ge=0)


def schema(db):
    hud.schema(db)
    db.execute('CREATE TABLE IF NOT EXISTS agent_hud_layout (singleton INTEGER PRIMARY KEY CHECK(singleton=1), revision INTEGER NOT NULL, payload TEXT NOT NULL)')


def shared_layout(db):
    row = db.execute('SELECT revision,payload FROM second_brain_hud_layout WHERE singleton=1').fetchone()
    if not row:
        return hud.defaults()
    stored = json.loads(row['payload'])
    if isinstance(stored, list):
        stored = {'widgets': stored}
    return {'revision': row['revision'], **stored}


def initialize(db, shared):
    # Copy the existing appearance once, then keep presentation independent.
    seed = {'widgets': shared['widgets'], 'agent_panel_expanded': shared.get('agent_panel_expanded', False)}
    db.execute('INSERT OR IGNORE INTO agent_hud_layout VALUES (1,0,?)', (json.dumps(seed),))


def project(row, shared):
    stored = json.loads(row['payload'])
    spaces = {w['operation']: w['workspace_ids'] for w in shared['widgets']}
    widgets = [{**w, 'workspace_ids': spaces.get(w['operation'], w['workspace_ids'])} for w in stored['widgets']]
    return {'revision': row['revision'], 'shared_revision': shared['revision'],
            'widgets': widgets, 'agent_panel_expanded': stored.get('agent_panel_expanded', False)}


def layout():
    with connection() as db:
        schema(db)
        shared = shared_layout(db)
        initialize(db, shared)
        row = db.execute('SELECT revision,payload FROM agent_hud_layout WHERE singleton=1').fetchone()
        return project(row, shared)


def save_layout(payload: Layout):
    known = {v['id'] for v in workspace_views.listing()['views']}
    if any(identity not in known for widget in payload.widgets for identity in widget.workspace_ids):
        raise HTTPException(409, 'A linked Space was removed. Reload before saving.')
    with connection() as db:
        schema(db)
        db.execute('BEGIN IMMEDIATE')
        shared = shared_layout(db)
        initialize(db, shared)
        row = db.execute('SELECT revision,payload FROM agent_hud_layout WHERE singleton=1').fetchone()
        if payload.revision != row['revision'] or payload.shared_revision != shared['revision']:
            raise HTTPException(409, 'HUD settings changed in another view. Reopen settings and try again.')
        widgets = [w.model_dump() for w in payload.widgets]
        shared_by_operation = {w['operation']: w for w in shared['widgets']}
        changed = False
        for widget in widgets:
            source = shared_by_operation.get(widget['operation'])
            if source is None and widget['workspace_ids']:
                # Keep a removed Second Brain widget hidden while retaining shared links.
                source = hud.Widget(id=str(uuid.uuid4()), operation=widget['operation'], hidden=True).model_dump()
                shared['widgets'].append(source)
                shared_by_operation[widget['operation']] = source
            if source is not None and source['workspace_ids'] != widget['workspace_ids']:
                source['workspace_ids'] = widget['workspace_ids']
                changed = True
        if changed:
            shared['revision'] += 1
            stored_shared = {k: v for k, v in shared.items() if k != 'revision'}
            db.execute('INSERT INTO second_brain_hud_layout VALUES (1,?,?) ON CONFLICT(singleton) DO UPDATE SET revision=excluded.revision,payload=excluded.payload', (shared['revision'], json.dumps(stored_shared)))
        previous = json.loads(row['payload'])
        expanded = payload.agent_panel_expanded if payload.agent_panel_expanded is not None else previous.get('agent_panel_expanded', False)
        stored = {'widgets': widgets, 'agent_panel_expanded': expanded}
        revision = row['revision'] + 1
        db.execute('UPDATE agent_hud_layout SET revision=?,payload=? WHERE singleton=1', (revision, json.dumps(stored)))
        return {'revision': revision, 'shared_revision': shared['revision'], **stored}


def data():
    result = hud.data()
    result['layout'] = layout()
    return result
