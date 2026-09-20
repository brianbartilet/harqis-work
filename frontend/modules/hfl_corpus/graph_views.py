"""Named owner graph views, with atomic revision checks in the profile database."""
import json
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from uuid import uuid4

from config import get_settings
from fastapi import HTTPException
from pydantic import BaseModel, Field, ConfigDict, FiniteFloat
from typing import Literal


class Position(BaseModel):
    x: FiniteFloat
    y: FiniteFloat
    pinned: bool = False


class Layout(BaseModel):
    positions: dict[str, Position] = Field(default_factory=dict)
    center: dict[Literal['x', 'y'], FiniteFloat] = Field(default_factory=dict)
    zoom: FiniteFloat = Field(default=1, gt=0)


class ViewState(BaseModel):
    model_config = ConfigDict(extra='forbid')
    density: Literal['100', '500', '1000', '0'] = '100'
    query: str = Field(default='', max_length=200)
    sources: list[str] = Field(default_factory=list, max_length=1000)
    since: str = Field(default='', max_length=10)
    until: str = Field(default='', max_length=10)
    rolling: int = Field(default=0, ge=0, le=36500)
    shared: bool = True
    group: Literal['relationships', 'source', 'date'] = 'relationships'
    enabled: list[Literal['entries', 'sources', 'daily', 'people', 'companies', 'tools', 'topics', 'objects', 'ideas', 'actions']] = Field(default_factory=list)
    focus: str | None = None
    layout: Layout = Field(default_factory=Layout)


class ViewWrite(BaseModel):
    name: str = Field(min_length=1, max_length=100, pattern=r'\S')
    state: ViewState
    revision: int = Field(default=0, ge=0)


@contextmanager
def connection():
    path = Path(get_settings().profile_store_path).expanduser()
    path.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(path, timeout=15)
    db.row_factory = sqlite3.Row
    try:
        with db:
            db.execute('CREATE TABLE IF NOT EXISTS graph_views (id TEXT PRIMARY KEY, name TEXT NOT NULL, state TEXT NOT NULL, revision INTEGER NOT NULL)')
            db.execute('CREATE TABLE IF NOT EXISTS graph_view_last (singleton INTEGER PRIMARY KEY CHECK(singleton=1), view_id TEXT)')
            yield db
    finally:
        db.close()


def decode(row):
    return {**dict(row), 'state': json.loads(row['state'])}


def listing():
    with connection() as db:
        last = db.execute('SELECT view_id FROM graph_view_last WHERE singleton=1').fetchone()
        return {'views': [decode(row) for row in db.execute('SELECT * FROM graph_views ORDER BY name COLLATE NOCASE, id')],
                'last_used': last[0] if last else None}


def save(payload, identity=None):
    state = json.dumps(payload.state.model_dump(), allow_nan=False)
    if len(state.encode()) > 8_000_000:
        raise HTTPException(413, 'View layout is too large to save')
    with connection() as db:
        if identity:
            changed = db.execute('UPDATE graph_views SET name=?, state=?, revision=revision+1 WHERE id=? AND revision=?',
                                 (payload.name.strip(), state, identity, payload.revision)).rowcount
            if not changed:
                raise HTTPException(409, 'View changed or was deleted in another browser. Reload it or save as new.')
        else:
            identity = uuid4().hex
            db.execute('INSERT INTO graph_views VALUES (?,?,?,1)', (identity, payload.name.strip(), state))
        db.execute('INSERT INTO graph_view_last VALUES (1,?) ON CONFLICT(singleton) DO UPDATE SET view_id=excluded.view_id', (identity,))
        return decode(db.execute('SELECT * FROM graph_views WHERE id=?', (identity,)).fetchone())


def select(identity):
    with connection() as db:
        if not db.execute('SELECT 1 FROM graph_views WHERE id=?', (identity,)).fetchone():
            raise HTTPException(404, 'Saved view no longer exists')
        db.execute('INSERT INTO graph_view_last VALUES (1,?) ON CONFLICT(singleton) DO UPDATE SET view_id=excluded.view_id', (identity,))


def delete(identity, revision):
    with connection() as db:
        if not db.execute('DELETE FROM graph_views WHERE id=? AND revision=?', (identity, revision)).rowcount:
            raise HTTPException(409, 'View changed or was deleted in another browser. Reload before deleting.')
        db.execute('DELETE FROM graph_view_last WHERE view_id=?', (identity,))
