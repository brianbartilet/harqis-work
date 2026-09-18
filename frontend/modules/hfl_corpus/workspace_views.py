"""Saved Corpus filters, independent of graph views in the owner profile database."""
import json
from datetime import date
from typing import Literal
from uuid import uuid4

from fastapi import HTTPException
from pydantic import BaseModel, ConfigDict, Field, field_validator

from modules.hfl_corpus.graph_views import connection
from modules.hfl_corpus.corpus import valid_source_filter_value


class WorkspaceState(BaseModel):
    model_config = ConfigDict(extra='forbid')
    q: str = Field(default='', max_length=2000)
    source: str = Field(default='', max_length=20000)
    date_field: Literal['created', 'updated', 'entry'] = 'created'
    date_from: str = ''
    date_to: str = ''
    rolling: Literal[0, 7, 30, 90] = 0
    sort: Literal['asc', 'desc'] = 'desc'
    page_size: Literal[20, 50, 100] = 20

    @field_validator('date_from', 'date_to')
    @classmethod
    def valid_date(cls, value):
        if value:
            date.fromisoformat(value)
        return value

    @field_validator('source')
    @classmethod
    def valid_sources(cls, value):
        parts = list(dict.fromkeys(part.strip() for part in value.split(',') if part.strip()))
        if any(not valid_source_filter_value(part) for part in parts):
            raise ValueError('Invalid source identifier')
        return ','.join(parts)


class WorkspaceWrite(BaseModel):
    name: str = Field(min_length=1, max_length=100, pattern=r'\S')
    state: WorkspaceState
    revision: int = Field(default=0, ge=0)


def schema(db):
    db.execute('CREATE TABLE IF NOT EXISTS corpus_workspace_views (id TEXT PRIMARY KEY, name TEXT NOT NULL, state TEXT NOT NULL, revision INTEGER NOT NULL)')
    db.execute('CREATE TABLE IF NOT EXISTS corpus_workspace_last (singleton INTEGER PRIMARY KEY CHECK(singleton=1), view_id TEXT)')


def decode(row):
    return {**dict(row), 'state': json.loads(row['state'])}


def listing():
    with connection() as db:
        schema(db)
        last = db.execute('SELECT view_id FROM corpus_workspace_last WHERE singleton=1').fetchone()
        return {'views': [decode(row) for row in db.execute('SELECT * FROM corpus_workspace_views ORDER BY name COLLATE NOCASE, id')], 'last_used': last[0] if last else None}


def save(payload, identity=None):
    state = payload.state.model_dump()
    if state['rolling']:
        state['date_from'] = state['date_to'] = ''
    encoded = json.dumps(state)
    with connection() as db:
        schema(db)
        if identity:
            changed = db.execute('UPDATE corpus_workspace_views SET name=?,state=?,revision=revision+1 WHERE id=? AND revision=?', (payload.name.strip(), encoded, identity, payload.revision)).rowcount
            if not changed:
                raise HTTPException(409, 'Workspace changed or was removed in another browser. Reload or save as new.')
        else:
            identity = uuid4().hex
            db.execute('INSERT INTO corpus_workspace_views VALUES (?,?,?,1)', (identity, payload.name.strip(), encoded))
        db.execute('INSERT INTO corpus_workspace_last VALUES (1,?) ON CONFLICT(singleton) DO UPDATE SET view_id=excluded.view_id', (identity,))
        return decode(db.execute('SELECT * FROM corpus_workspace_views WHERE id=?', (identity,)).fetchone())


def select(identity):
    with connection() as db:
        schema(db)
        if not db.execute('SELECT 1 FROM corpus_workspace_views WHERE id=?', (identity,)).fetchone():
            raise HTTPException(404, 'Saved workspace no longer exists')
        db.execute('INSERT INTO corpus_workspace_last VALUES (1,?) ON CONFLICT(singleton) DO UPDATE SET view_id=excluded.view_id', (identity,))


def delete(identity, revision):
    with connection() as db:
        schema(db)
        if not db.execute('DELETE FROM corpus_workspace_views WHERE id=? AND revision=?', (identity, revision)).rowcount:
            raise HTTPException(409, 'Workspace changed or was removed in another browser. Reload before removing.')
        db.execute('DELETE FROM corpus_workspace_last WHERE view_id=?', (identity,))
