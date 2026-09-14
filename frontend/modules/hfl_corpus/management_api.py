"""Typed external commands for actions and Memory Signal records.

Mounted beneath the corpus router so every operation inherits bearer auth.
These commands persist intent; enabling agents is a separate owner operation.
"""
from __future__ import annotations

from datetime import date
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, BackgroundTasks, HTTPException, Query, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field

from modules.hfl_corpus import timeline
from modules.hfl_corpus.memory_pins import get_memory_pin_store
from modules.profile.store import get_profile_store
from workflows.hfl.timeline_store import FollowUpConflict


router = APIRouter(tags=["hfl-management"])


class Command(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ActionSource(Command):
    path: str
    entry_id: str


class CreateAction(Command):
    request_id: UUID = Field(description="Caller-generated UUID. Reuse unchanged on retry.")
    title: str = Field(min_length=1, max_length=200)
    expected_outcome: str = Field(min_length=1, max_length=3000)
    review_date: str = ""
    due_date: str = ""
    prompt: str = Field(default="", max_length=20000)
    notes: str = Field(default="", max_length=6000)
    source: ActionSource | None = None


class UpdateAction(Command):
    version: int = Field(ge=1, strict=True, description="Version returned by the latest read; stale versions return 409.")
    title: str | None = Field(default=None, min_length=1, max_length=200)
    expected_outcome: str | None = Field(default=None, min_length=1, max_length=3000)
    review_date: str | None = None
    due_date: str | None = None
    prompt: str | None = Field(default=None, max_length=20000)
    notes: str | None = Field(default=None, max_length=6000)
    status: Literal["open", "active", "in_progress", "incomplete", "done", "dismissed"] | None = None
    completion_note: str | None = Field(default=None, max_length=3000)


class SaveCategory(Command):
    name: str = Field(min_length=1, max_length=60)
    color: str = Field(description="A color from GET /categories palette.")
    instructions: str = Field(default="", max_length=20000)


class UpdateCategory(Command):
    name: str | None = Field(default=None, min_length=1, max_length=60)
    color: str | None = None
    instructions: str | None = Field(default=None, max_length=20000)


class CreatePin(Command):
    category_id: int = Field(gt=0, strict=True)
    start_date: date
    end_date: date
    title: str = Field(min_length=1, max_length=2000)
    note: str = Field(default="", max_length=2000)
    prompt: str = Field(default="", max_length=20000)


class UpdatePin(Command):
    category_id: int | None = Field(default=None, gt=0, strict=True)
    start_date: date | None = None
    end_date: date | None = None
    title: str | None = Field(default=None, min_length=1, max_length=2000)
    note: str | None = Field(default=None, max_length=2000)
    prompt: str | None = Field(default=None, max_length=20000)


def _changes(payload: Command) -> dict:
    changes = payload.model_dump(mode="json", exclude_unset=True)
    if any(value is None for value in changes.values()):
        raise HTTPException(422, "Use an empty string to clear text or dates; null is not supported.")
    return changes


def _call(operation, *args, **kwargs):
    try:
        return operation(*args, **kwargs)
    except KeyError:
        raise HTTPException(404, "Record not found.") from None
    except FollowUpConflict as exc:
        raise HTTPException(409, str(exc)) from None
    except (ValueError, TypeError) as exc:
        raise HTTPException(422, str(exc)) from None


@router.get("/actions")
async def list_actions(request: Request, closed: bool = False, offset: int = Query(0, ge=0)):
    """List up to 500 open or closed actions; continue using offset and total."""
    return await timeline.followup_list(request, closed, offset)


@router.post("/actions", status_code=201, responses={200: {"description": "Idempotent replay"}, 409: {"description": "Request ID already used with different content"}})
async def create_action(payload: CreateAction):
    """Create standalone or entry-linked intent with scheduled agent execution disabled."""
    raw = payload.model_dump(mode="json")
    source = raw.pop("source")
    if source:
        entry = await timeline.evidence(source["path"], source["entry_id"])
        source.update(title=entry.moment or entry.header, date=entry.header[:10])
    raw["agent_enabled"] = False
    item, duplicate = _call(timeline.store().create, raw, actor="owner-api", source=source)
    return JSONResponse({"item": item, "duplicate": duplicate}, status_code=200 if duplicate else 201)


@router.get("/actions/{action_id}")
def get_action(action_id: str):
    return {"item": _call(timeline.store().get, action_id)}


@router.patch("/actions/{action_id}", responses={409: {"description": "Stale version"}})
def update_action(action_id: str, payload: UpdateAction, background_tasks: BackgroundTasks):
    """Edit or complete/dismiss an action. Completion retains the existing HFL receipt behavior."""
    store = timeline.store()
    item = _call(store.update, action_id, _changes(payload), actor="owner-api")
    if any(r["followup_id"] == action_id and r["version"] == item["version"] for r in store.receipts(pending_only=True)):
        background_tasks.add_task(timeline.write_completion, action_id, item["version"], store=store)
    return {"item": item}


@router.get("/actions/{action_id}/history")
def action_history(action_id: str):
    return {"history": _call(timeline.store().history, action_id)}


def _category(store, category_id: int) -> dict:
    snapshot = store.snapshot()
    for category in snapshot["categories"] + snapshot["archived_categories"]:
        if category["id"] == category_id:
            return category
    raise HTTPException(404, "Category not found.")


@router.get("/categories")
def list_categories():
    snapshot = get_memory_pin_store().snapshot()
    return {key: snapshot[key] for key in ("categories", "archived_categories", "palette")}


@router.post("/categories", status_code=201)
def create_category(payload: SaveCategory):
    store = get_memory_pin_store()
    category_id = _call(store.save_category, category_id=None, **payload.model_dump())
    return {"category": _category(store, category_id)}


@router.get("/categories/{category_id}")
def get_category(category_id: int):
    return {"category": _category(get_memory_pin_store(), category_id)}


@router.patch("/categories/{category_id}")
def update_category(category_id: int, payload: UpdateCategory):
    store = get_memory_pin_store()
    existing = _category(store, category_id)
    fields = {key: existing[key] for key in ("name", "color", "instructions")}
    _call(store.save_category, category_id=category_id, **(fields | _changes(payload)))
    return {"category": _category(store, category_id)}


@router.post("/categories/{category_id}/archive")
def archive_category(category_id: int):
    """Archive a category and hide its pins without deleting their history."""
    store = get_memory_pin_store()
    _category(store, category_id)
    _call(store.archive_category, category_id)
    return {"category": _category(store, category_id)}


def _pin(store, pin_id: int) -> dict:
    for pin in store.snapshot()["ranges"]:
        if pin["id"] == pin_id:
            return pin
    raise HTTPException(404, "Pin not found in an active category.")


def _validate_pin_dates(fields):
    start, end = sorted(date.fromisoformat(fields[key]) for key in ("start_date", "end_date"))
    birthdate = get_profile_store().get().birthdate
    if birthdate and start < date.fromisoformat(birthdate):
        raise HTTPException(422, "Pinned dates cannot be earlier than your birthdate.")
    today = date.today()
    try:
        limit = today.replace(year=today.year + 5)
    except ValueError:
        limit = today.replace(year=today.year + 5, day=28)
    if end > limit:
        raise HTTPException(422, f"Pinned dates cannot be later than {limit.isoformat()}.")


@router.get("/pins")
def list_pins(category_id: int | None = Query(None, gt=0)):
    pins = get_memory_pin_store().snapshot()["ranges"]
    return {"pins": [pin for pin in pins if category_id is None or pin["category_id"] == category_id]}


@router.post("/pins", status_code=201)
def create_pin(payload: CreatePin):
    """Pin a date or inclusive date range, with agent execution disabled even with a prompt."""
    fields = payload.model_dump(mode="json")
    _validate_pin_dates(fields)
    store = get_memory_pin_store()
    pin_id = _call(store.save_range, range_id=None, agent_enabled=False, **fields)
    return {"pin": _pin(store, pin_id)}


@router.get("/pins/{pin_id}")
def get_pin(pin_id: int):
    return {"pin": _pin(get_memory_pin_store(), pin_id)}


@router.patch("/pins/{pin_id}")
def update_pin(pin_id: int, payload: UpdatePin):
    store = get_memory_pin_store()
    existing = _pin(store, pin_id)
    fields = {key: existing[key] for key in ("category_id", "start_date", "end_date", "title", "note", "prompt", "execution_hour")}
    fields.update(_changes(payload))
    _validate_pin_dates(fields)
    _call(store.save_range, range_id=pin_id, **fields)
    return {"pin": _pin(store, pin_id)}


@router.delete("/pins/{pin_id}")
def delete_pin(pin_id: int):
    store = get_memory_pin_store()
    _pin(store, pin_id)
    store.delete_range(pin_id)
    return {"deleted": True, "pin_id": pin_id}
