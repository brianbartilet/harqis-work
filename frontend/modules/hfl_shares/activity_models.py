"""Versioned recipe controls. Empty legacy controls deliberately mean entries only."""
from typing import Literal
import json

from pydantic import BaseModel, ConfigDict, Field


class GraphPoint(BaseModel):
    model_config = ConfigDict(extra='forbid', allow_inf_nan=False)
    x: float
    y: float


class GraphPosition(GraphPoint):
    manual: bool = False


class GraphViewport(GraphPoint):
    zoom: float = Field(ge=.01, le=4)


class GraphView(BaseModel):
    model_config = ConfigDict(extra='forbid')
    preset: Literal['timeline', 'sources', 'people', 'tools', 'companies', 'mindmap'] = 'timeline'
    animation: Literal['off', 'breathing', 'ripple', 'drift'] = 'off'
    hidden_kinds: list[str] = Field(default_factory=list, max_length=100)
    positions: dict[str, GraphPosition] = Field(default_factory=dict, max_length=20000)
    viewport: GraphViewport | None = None
    animation_time: float = Field(default=0, ge=0, allow_inf_nan=False)


class ActivitySelection(BaseModel):
    model_config = ConfigDict(extra='forbid')
    version: Literal[1] = 1
    sections: list[Literal['entries', 'actions', 'ideas', 'boards', 'plans', 'graph']] = Field(default_factory=lambda: ['entries'])
    workspace_ids: list[str] = Field(default_factory=list, max_length=100)
    excluded_ids: list[str] = Field(default_factory=list, max_length=20000)
    excluded_labels: dict[str, str] = Field(default_factory=dict, max_length=20000)
    include_completed: bool = False
    include_dismissed: bool = False
    outside_board_ids: list[str] = Field(default_factory=list, max_length=1000)
    automatic: list[Literal['entries', 'actions', 'ideas', 'boards', 'plans']] = Field(default_factory=list)
    approved_ids: dict[str, list[str]] | None = None
    graph_view: GraphView = Field(default_factory=GraphView)


def selection(configuration):
    return ActivitySelection.model_validate(configuration.activity or {})


def from_form(form):
    if form.get('activity_version') != '1':
        return {}
    return ActivitySelection(
        sections=form.getlist('activity_sections'),
        workspace_ids=[v for v in str(form.get('workspace_ids') or '').split(',') if v],
        excluded_ids=form.getlist('excluded_object_ids'),
        excluded_labels=json.loads(str(form.get('excluded_object_labels') or '{}')),
        include_completed=form.get('include_completed') == 'on',
        include_dismissed=form.get('include_dismissed') == 'on',
        outside_board_ids=form.getlist('outside_board_ids'),
        automatic=form.getlist('automatic_sections'),
        graph_view=json.loads(str(form.get('graph_view') or '{}')),
    ).model_dump()


def live_configuration(configuration, snapshot):
    from dataclasses import replace
    if not configuration.live_updates:
        return None
    if not configuration.activity:
        return configuration
    controls = selection(configuration)
    controls.approved_ids = {'entries': [e.id for e in snapshot.entries]}
    for kind in ('actions', 'ideas', 'boards', 'plans'):
        controls.approved_ids[kind] = [o['id'] for o in snapshot.activity.get(kind, [])]
    # Also pin board members for approved-only boards.
    controls.approved_ids['members'] = [n['id'] for b in snapshot.activity.get('boards', []) for n in b['graph']['nodes']]
    return replace(configuration, activity=controls.model_dump())
