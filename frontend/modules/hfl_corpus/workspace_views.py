"""Saved Corpus filters, independent of graph views in the owner profile database."""
import json
from datetime import date, datetime, timezone
from typing import Literal
from uuid import uuid4

from fastapi import HTTPException
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from modules.hfl_corpus.graph_views import connection
from modules.profile.store import get_profile_store
from modules.hfl_corpus.memory_pins import PIN_COLORS
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

    @model_validator(mode='after')
    def valid_range(self):
        if not self.rolling and self.date_from and self.date_to and self.date_from > self.date_to:
            raise ValueError('The start date must not follow the end date.')
        return self

    @field_validator('source')
    @classmethod
    def valid_sources(cls, value):
        parts = list(dict.fromkeys(part.strip() for part in value.split(',') if part.strip()))
        if any(not valid_source_filter_value(part) for part in parts):
            raise ValueError('Invalid source identifier')
        return ','.join(parts)


class TimeBlock(BaseModel):
    model_config = ConfigDict(extra='forbid')
    days: list[int] = Field(min_length=1, max_length=7)
    start: str = Field(pattern=r'^([01]\d|2[0-3]):[0-5]\d$')
    end: str = Field(pattern=r'^([01]\d|2[0-3]):[0-5]\d$')

    @model_validator(mode='after')
    def valid_block(self):
        if any(day < 0 or day > 6 for day in self.days) or self.start == self.end:
            raise ValueError('Choose weekdays and different start/end times.')
        self.days = sorted(set(self.days))
        return self


class ViewPreferences(BaseModel):
    model_config = ConfigDict(extra='forbid')
    manual: list[str] = Field(default_factory=list, max_length=30)
    dynamic: bool = False
    timezone: str = 'Asia/Singapore'
    revision: int = Field(default=0, ge=0)
    applied: WorkspaceState = Field(default_factory=WorkspaceState)

    @field_validator('timezone')
    @classmethod
    def valid_timezone(cls, value):
        try:
            ZoneInfo(value)
        except (ZoneInfoNotFoundError, ValueError) as exc:
            raise ValueError('Choose a valid timezone, such as Asia/Singapore.') from exc
        return value


class WorkspaceWrite(BaseModel):
    color: str | None = None

    @field_validator('color')
    @classmethod
    def valid_color(cls, value):
        if value is not None and value not in PIN_COLORS:
            raise ValueError('Choose a color from the Memory Signal palette.')
        return value

    name: str = Field(min_length=1, max_length=100, pattern=r'\S')
    state: WorkspaceState
    schedule: list[TimeBlock] | None = Field(default=None, max_length=50)
    revision: int = Field(default=0, ge=0)


def schema(db):
    db.execute('CREATE TABLE IF NOT EXISTS corpus_view_preferences (singleton INTEGER PRIMARY KEY CHECK(singleton=1), payload TEXT NOT NULL)')
    db.execute('CREATE TABLE IF NOT EXISTS corpus_view_schedules (view_id TEXT PRIMARY KEY, payload TEXT NOT NULL)')
    db.execute('CREATE TABLE IF NOT EXISTS corpus_workspace_views (id TEXT PRIMARY KEY, name TEXT NOT NULL, state TEXT NOT NULL, revision INTEGER NOT NULL)')
    columns = {row[1] for row in db.execute('PRAGMA table_info(corpus_workspace_views)')}
    if 'color' not in columns:
        db.execute("ALTER TABLE corpus_workspace_views ADD COLUMN color TEXT NOT NULL DEFAULT '#3b82f6'")
        for index, row in enumerate(db.execute('SELECT id FROM corpus_workspace_views ORDER BY id').fetchall()):
            db.execute('UPDATE corpus_workspace_views SET color=? WHERE id=?', (PIN_COLORS[index % len(PIN_COLORS)], row[0]))
    db.execute('CREATE TABLE IF NOT EXISTS corpus_workspace_last (singleton INTEGER PRIMARY KEY CHECK(singleton=1), view_id TEXT)')


def decode(row):
    return {**dict(row), 'state': json.loads(row['state'])}


def listing():
    profile_timezone = get_profile_store().get().timezone
    with connection() as db:
        schema(db)
        last = db.execute('SELECT view_id FROM corpus_workspace_last WHERE singleton=1').fetchone()
        views = [decode(row) for row in db.execute('SELECT * FROM corpus_workspace_views ORDER BY name COLLATE NOCASE, id')]
        schedules = {row[0]: json.loads(row[1]) for row in db.execute('SELECT * FROM corpus_view_schedules')}
        for view in views:
            view['schedule'] = schedules.get(view['id'], [])
        stored = db.execute('SELECT payload FROM corpus_view_preferences WHERE singleton=1').fetchone()
        prefs = json.loads(stored[0]) if stored else ViewPreferences(manual=[last[0]] if last and last[0] else []).model_dump()
        prefs = ViewPreferences.model_validate(prefs).model_dump()
        prefs['timezone'] = profile_timezone
        prefs['manual'] = [identity for identity in prefs['manual'] if any(v['id'] == identity for v in views)]
        active = active_views(views, prefs)
        return {'palette': list(PIN_COLORS), 'views': views, 'last_used': last[0] if last else None, 'preferences': prefs, 'active': active, 'today': datetime.now(ZoneInfo(prefs['timezone'])).date().isoformat()}


def save(payload, identity=None):
    creating = identity is None
    state = payload.state.model_dump()
    if state['rolling']:
        state['date_from'] = state['date_to'] = ''
    encoded = json.dumps(state)
    with connection() as db:
        schema(db)
        if identity:
            changed = db.execute('UPDATE corpus_workspace_views SET name=?,state=?,revision=revision+1 WHERE id=? AND revision=?', (payload.name.strip(), encoded, identity, payload.revision)).rowcount
            if not changed:
                raise HTTPException(409, 'View changed or was removed in another browser. Reload or save as new.')
        else:
            identity = uuid4().hex
            color = payload.color or PIN_COLORS[db.execute('SELECT COUNT(*) FROM corpus_workspace_views').fetchone()[0] % len(PIN_COLORS)]
            db.execute('INSERT INTO corpus_workspace_views (id,name,state,revision,color) VALUES (?,?,?,1,?)', (identity, payload.name.strip(), encoded, color))
        if payload.color is not None:
            db.execute('UPDATE corpus_workspace_views SET color=? WHERE id=?', (payload.color, identity))
        db.execute('INSERT INTO corpus_workspace_last VALUES (1,?) ON CONFLICT(singleton) DO UPDATE SET view_id=excluded.view_id', (identity,))
        row = db.execute('SELECT payload FROM corpus_view_preferences WHERE singleton=1').fetchone()
        if row:
            preferences = json.loads(row[0])
            preferences['revision'] += 1
            if creating:
                preferences.update(manual=[identity], dynamic=False, applied=WorkspaceState().model_dump())
            db.execute('UPDATE corpus_view_preferences SET payload=? WHERE singleton=1', (json.dumps(preferences),))
        if payload.schedule is not None:
            db.execute('INSERT INTO corpus_view_schedules VALUES (?,?) ON CONFLICT(view_id) DO UPDATE SET payload=excluded.payload', (identity, json.dumps([block.model_dump() for block in payload.schedule])))
        result = decode(db.execute('SELECT * FROM corpus_workspace_views WHERE id=?', (identity,)).fetchone())
        row = db.execute('SELECT payload FROM corpus_view_schedules WHERE view_id=?', (identity,)).fetchone()
        result['schedule'] = json.loads(row[0]) if row else []
        return result


def select(identity):
    with connection() as db:
        schema(db)
        if not db.execute('SELECT 1 FROM corpus_workspace_views WHERE id=?', (identity,)).fetchone():
            raise HTTPException(404, 'Saved view no longer exists')
        db.execute('INSERT INTO corpus_workspace_last VALUES (1,?) ON CONFLICT(singleton) DO UPDATE SET view_id=excluded.view_id', (identity,))


def delete(identity, revision):
    with connection() as db:
        schema(db)
        if not db.execute('DELETE FROM corpus_workspace_views WHERE id=? AND revision=?', (identity, revision)).rowcount:
            raise HTTPException(409, 'View changed or was removed in another browser. Reload before removing.')
        db.execute('DELETE FROM corpus_workspace_last WHERE view_id=?', (identity,))
        db.execute('DELETE FROM corpus_view_schedules WHERE view_id=?', (identity,))
        row = db.execute('SELECT payload FROM corpus_view_preferences WHERE singleton=1').fetchone()
        if row:
            preferences = json.loads(row[0])
            preferences['manual'] = [value for value in preferences['manual'] if value != identity]
            preferences['revision'] += 1
            if not any(json.loads(row[0]) for row in db.execute('SELECT payload FROM corpus_view_schedules')):
                preferences['dynamic'] = False
            db.execute('UPDATE corpus_view_preferences SET payload=? WHERE singleton=1', (json.dumps(preferences),))


def active_views(views, preferences, now=None):
    if not preferences['dynamic']:
        return preferences['manual']
    local = (now or datetime.now(timezone.utc)).astimezone(ZoneInfo(preferences['timezone']))
    day, minute = local.weekday(), local.strftime('%H:%M')
    active = []
    for view in views:
        for block in view.get('schedule', []):
            start, end, days = block['start'], block['end'], block['days']
            current = day in days and start <= minute < end if start < end else (day in days and minute >= start) or ((day-1) % 7 in days and minute < end)
            if current:
                active.append(view['id'])
                break
    return active


def save_preferences(payload):
    profile_timezone = get_profile_store().get().timezone
    with connection() as db:
        schema(db)
        db.execute('BEGIN IMMEDIATE')
        row = db.execute('SELECT payload FROM corpus_view_preferences WHERE singleton=1').fetchone()
        revision = json.loads(row[0]).get('revision', 0) if row else 0
        if revision != payload.revision:
            raise HTTPException(409, 'View settings changed in another tab. Reload and retry.')
        valid = {row[0] for row in db.execute('SELECT id FROM corpus_workspace_views')}
        if any(identity not in valid for identity in payload.manual):
            raise HTTPException(409, 'A selected view was removed. Reload and retry.')
        if payload.dynamic and not any(json.loads(row[0]) for row in db.execute('SELECT s.payload FROM corpus_view_schedules s JOIN corpus_workspace_views v ON v.id=s.view_id')):
            raise HTTPException(422, 'Add a time block in Edit View → Assign schedules before enabling Dynamic mode.')
        values = payload.model_dump()
        values['timezone'] = profile_timezone
        values['manual'] = list(dict.fromkeys(values['manual']))
        values['revision'] = revision + 1
        db.execute('INSERT INTO corpus_view_preferences VALUES (1,?) ON CONFLICT(singleton) DO UPDATE SET payload=excluded.payload', (json.dumps(values),))
    return listing()


def selection_url(snapshot, identities=None, dynamic=False):
    from urllib.parse import urlencode
    from modules.hfl_corpus.view_scope import resolved
    identities = snapshot['active'] if identities is None else identities
    chosen = [v for v in snapshot['views'] if v['id'] in identities]
    today = datetime.now(ZoneInfo(snapshot['preferences']['timezone'])).date()
    applied = snapshot['preferences'].get('applied', WorkspaceState().model_dump())
    if not dynamic and len(chosen) == 1 and applied == WorkspaceState().model_dump():
        return '/hfl-corpus?' + urlencode({**chosen[0]['state'], 'workspace': chosen[0]['id'], 'workspace_revision': snapshot['preferences']['revision']})
    scope = {'any': [resolved(v['state'], today) for v in chosen], 'all': resolved(applied, today)}
    return '/hfl-corpus?' + urlencode({**applied, 'views': ','.join(v['id'] for v in chosen), 'scope': json.dumps(scope, separators=(',', ':')), 'dynamic': int(dynamic), 'workspace_revision': snapshot['preferences']['revision']})
