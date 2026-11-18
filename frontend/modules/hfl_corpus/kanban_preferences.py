"""Per-owner, per-status Kanban sorting in the existing profile database."""
from typing import Literal

from fastapi import HTTPException
from pydantic import BaseModel, ConfigDict, Field

from modules.hfl_corpus.graph_views import connection


STATUSES = ('open', 'active', 'in_progress', 'incomplete', 'done', 'dismissed')


class SortWrite(BaseModel):
    model_config = ConfigDict(extra='forbid')
    status: Literal['open', 'active', 'in_progress', 'incomplete', 'done', 'dismissed']
    sort: Literal['updated_desc', 'updated_asc', 'created_desc', 'created_asc', 'name']
    revision: int = Field(ge=0, strict=True)


def initialize(db):
    db.execute('''CREATE TABLE IF NOT EXISTS kanban_sort_preferences (
        owner TEXT NOT NULL, status TEXT NOT NULL, sort TEXT NOT NULL,
        revision INTEGER NOT NULL, PRIMARY KEY(owner, status))''')


def listing(owner):
    with connection() as db:
        initialize(db)
        values = {s: {'sort': 'updated_desc', 'revision': 0} for s in STATUSES}
        for row in db.execute('SELECT status,sort,revision FROM kanban_sort_preferences WHERE owner=?', (owner,)):
            values[row['status']] = {'sort': row['sort'], 'revision': row['revision']}
        return {'sorting': values}


def save(owner, payload: SortWrite):
    with connection() as db:
        initialize(db)
        db.execute('BEGIN IMMEDIATE')
        row = db.execute('SELECT revision FROM kanban_sort_preferences WHERE owner=? AND status=?',
                         (owner, payload.status)).fetchone()
        if payload.revision != (row['revision'] if row else 0):
            raise HTTPException(409, 'Sorting changed elsewhere. Refresh and choose again.')
        db.execute('''INSERT INTO kanban_sort_preferences VALUES (?,?,?,?)
            ON CONFLICT(owner,status) DO UPDATE SET sort=excluded.sort,revision=excluded.revision''',
                   (owner, payload.status, payload.sort, payload.revision + 1))
    return listing(owner)
