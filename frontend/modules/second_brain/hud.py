"""Portable HUD layout and read-only projections. No source task execution."""
import ast
import json
import os
import threading
import time
from pathlib import Path
from typing import Literal
from urllib.parse import urlsplit

from fastapi import HTTPException
from pydantic import BaseModel, ConfigDict, Field, model_validator

from modules.hfl_corpus.graph_views import connection
from modules.hfl_corpus import workspace_views
from modules.second_brain.service import snapshot
from workflows.second_brain.registry import OPERATIONS

SIZES = {'1x1': 'Small square', '1x2': 'One column medium', '1x4': 'One column tall',
         '2x1': 'Two column short', '2x2': 'Two column square', '2x4': 'Two column tall',
         '3x3': 'Large square', '3x4': 'Half screen'}
ROOT = Path(__file__).resolve().parents[3]


class Widget(BaseModel):
    model_config = ConfigDict(extra='forbid')
    id: str = Field(min_length=1, max_length=64, pattern=r'^[a-zA-Z0-9_-]+$')
    operation: str
    size: Literal['1x1', '1x2', '1x4', '2x1', '2x2', '2x4', '3x3', '3x4'] = '2x2'
    hidden: bool = False
    animation: Literal['static', 'marquee', 'typing'] = 'static'
    workspace_ids: list[str] = Field(default_factory=list, max_length=30)
    dashboard_url: str = Field(default='', max_length=2000)

    @model_validator(mode='after')
    def validate_source(self):
        if self.operation not in OPERATIONS and self.operation not in {'context', 'monitoring'}:
            raise ValueError('Choose an available widget.')
        if self.dashboard_url:
            base = kibana_base()
            parsed = urlsplit(self.dashboard_url)
            if not base or parsed.scheme not in {'http', 'https'} or parsed.netloc != urlsplit(base).netloc or parsed.scheme != urlsplit(base).scheme or parsed.username or parsed.password:
                raise ValueError('Use a dashboard URL from the configured Kibana server.')
            if not parsed.path.startswith(('/app/dashboards', '/s/')):
                raise ValueError('Use a Kibana dashboard share URL.')
        return self


class Layout(BaseModel):
    model_config = ConfigDict(extra='forbid')
    revision: int = Field(default=0, ge=0)
    widgets: list[Widget] = Field(default_factory=list, max_length=80)

    @model_validator(mode='after')
    def unique_ids(self):
        if len({w.id for w in self.widgets}) != len(self.widgets):
            raise ValueError('Widget identities must be unique.')
        return self


def kibana_base():
    value = os.environ.get('KIBANA_HOST', '').rstrip('/')
    parsed = urlsplit(value)
    return value if parsed.scheme in {'http', 'https'} and parsed.netloc and not parsed.username and not parsed.password else ''


def defaults():
    sources = [('hud.hud_radar.show_daily_radar', '3x4'),
               ('hud.hud_calendar.show_calendar_information', '1x2'),
               ('hud.hud_jira.show_jira_board', '2x2'),
               ('hud.hud_logs.get_failed_jobs', '1x2'), ('context', '2x2')]
    return Layout(widgets=[Widget(id=f'initial-{i}', operation=op, size=size) for i, (op, size) in enumerate(sources)]).model_dump()


def schema(db):
    db.execute('CREATE TABLE IF NOT EXISTS second_brain_hud_layout (singleton INTEGER PRIMARY KEY CHECK(singleton=1), revision INTEGER NOT NULL, payload TEXT NOT NULL)')


def layout():
    with connection() as db:
        schema(db)
        row = db.execute('SELECT revision,payload FROM second_brain_hud_layout WHERE singleton=1').fetchone()
        return {'revision': row['revision'], 'widgets': json.loads(row['payload'])} if row else defaults()


def save_layout(payload: Layout):
    known = {v['id'] for v in workspace_views.listing()['views']}
    if any(identity not in known for widget in payload.widgets for identity in widget.workspace_ids):
        raise HTTPException(409, 'A linked Space was removed. Reload before saving.')
    with connection() as db:
        schema(db)
        db.execute('BEGIN IMMEDIATE')
        row = db.execute('SELECT revision FROM second_brain_hud_layout WHERE singleton=1').fetchone()
        if payload.revision != (row['revision'] if row else 0):
            raise HTTPException(409, 'HUD changed in another tab. Reload before saving.')
        revision = payload.revision + 1
        widgets = [w.model_dump() for w in payload.widgets]
        db.execute('INSERT INTO second_brain_hud_layout VALUES (1,?,?) ON CONFLICT(singleton) DO UPDATE SET revision=excluded.revision,payload=excluded.payload', (revision, json.dumps(widgets)))
        return {'revision': revision, 'widgets': widgets}


def inventory():
    """Read enabled schedule entries without importing Windows collectors."""
    tree = ast.parse((ROOT / 'workflows/hud/tasks_config.py').read_text(encoding='utf-8'))
    schedules = {}
    for node in tree.body:
        if not isinstance(node, ast.Assign) or not isinstance(node.value, ast.Dict):
            continue
        for key, entry in zip(node.value.keys, node.value.values):
            if not isinstance(entry, ast.Dict):
                continue
            values = {k.value: v for k, v in zip(entry.keys, entry.values) if isinstance(k, ast.Constant)}
            task = values.get('task')
            if isinstance(task, ast.Constant):
                schedules.setdefault(task.value, []).append({'name': ast.literal_eval(key), 'schedule': ast.unparse(values.get('schedule')), 'options': ast.unparse(values.get('options'))})
    result = [{'operation_id': 'context', 'label': 'Context feed', 'source_task': '', 'schedules': []},
              {'operation_id': 'monitoring', 'label': 'Monitoring / Kibana', 'source_task': '', 'schedules': []}]
    for op in OPERATIONS.values():
        result.append({'operation_id': op.operation_id, 'label': op.label, 'source_task': op.source_task,
                       'schedules': schedules.get(op.source_task, []), 'refresh_minutes': op.refresh_minutes})
    return result


_projection_cache = {'until': 0, 'items': {}, 'error': ''}
_projection_lock = threading.Lock()


def projections():
    """One bounded shared read per 30 seconds, not one ES scan per panel."""
    from workflows.second_brain.hud_projection import _projection_source, HUD_PROJECTION_INDEX
    with _projection_lock:
        if time.monotonic() < _projection_cache['until']:
            return _projection_cache['items'], _projection_cache['error']
        try:
            from core.apps.es_logging.app.elasticsearch import get_index_data
            from workflows.second_brain.migrate_hud_dumps import MIGRATION_INDEX
            rows = [_projection_source(row) for row in get_index_data(HUD_PROJECTION_INDEX, fetch_docs=250, timeout=8)]
            latest = {}
            for row in rows:
                key = row.get('source_task', '')
                if str(row.get('captured_at', '')) > str(latest.get(key, {}).get('captured_at', '')):
                    latest[key] = row
            try:
                migrated = get_index_data(MIGRATION_INDEX, fetch_docs=250, timeout=8)
            except RuntimeError as exc:
                if 'Search failed (404)' not in str(exc):
                    raise
                migrated = []  # Backfill is optional on new installations.
            for raw in migrated:
                row = _projection_source(raw)
                key = row.get('source_task', '')
                payload = latest.get(key, {}).get('payload') or {}
                if not (payload.get('text') or payload.get('feed_text')):
                    latest[key] = row
            _projection_cache.update(items=latest, error='')
        except Exception:
            _projection_cache['error'] = 'HUD source storage is unavailable. Last captured data is retained.'
        _projection_cache['until'] = time.monotonic() + 30
        return _projection_cache['items'], _projection_cache['error']


def data():
    from workflows.second_brain.hud_projection import collect_hud_projection
    brain = snapshot()
    sources, error = projections()
    items = {}
    for op in OPERATIONS.values():
        if op.source_task:
            items[op.operation_id] = [item.to_payload() for item in collect_hud_projection(
                **op.kwargs, correlation_id='web-hud', projection=sources.get(op.source_task))]
        else:
            items[op.operation_id] = [item for item in brain['items'] if item.get('operation_id') == op.operation_id]
    return {'layout': layout(), 'spaces': workspace_views.listing(), 'items': items,
            'context': brain['items'], 'decision': brain['decision'], 'source_error': error,
            'automatic_feed': brain['automatic_feed'], 'kibana_url': kibana_base()}
