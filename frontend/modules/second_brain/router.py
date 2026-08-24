"""Authenticated page, commands, settings, snapshots, and SSE feed."""

from __future__ import annotations

import asyncio
import json
import re
import uuid

from fastapi import APIRouter, Form, Query, Request
from fastapi.responses import HTMLResponse, JSONResponse, StreamingResponse

import celery_client
from auth import get_current_user
from modules.second_brain.service import changes_after, get_second_brain_store, snapshot
from web import page_context, require_user, templates


router = APIRouter()
_MODE_SPLIT = re.compile(r"[,+\s]+")


def _view_context(request: Request, user: str) -> dict:
    data = snapshot(client="web")
    return page_context(request, user, "second_brain", second_brain=data)


def _unauthorized() -> JSONResponse:
    return JSONResponse({"error": "unauthorized"}, status_code=401)


def _dispatch_reconcile(correlation_id: str) -> str:
    return celery_client.dispatch(
        task_path="workflows.second_brain.tasks.reconcile.reconcile_second_brain",
        kwargs={"correlation_id": correlation_id},
        queue="host",
    )


@router.get("/second-brain", response_class=HTMLResponse)
async def second_brain_page(request: Request):
    user, redirect = require_user(request)
    if redirect:
        return redirect
    return templates.TemplateResponse(
        request,
        "modules/second_brain/index.html",
        _view_context(request, user),
    )


@router.get("/second-brain/feed-fragment", response_class=HTMLResponse)
async def second_brain_fragment(request: Request):
    user, redirect = require_user(request)
    if redirect:
        return HTMLResponse("", status_code=401)
    return templates.TemplateResponse(
        request,
        "modules/second_brain/_shell.html",
        _view_context(request, user),
    )


@router.get("/second-brain/api/feed")
async def second_brain_snapshot(request: Request, client: str = Query("web"), limit: int = Query(100, ge=1, le=500)):
    if not get_current_user(request):
        return _unauthorized()
    try:
        return JSONResponse(snapshot(client=client, limit=limit))
    except PermissionError as exc:
        return JSONResponse({"error": str(exc)}, status_code=403)
    except ValueError as exc:
        return JSONResponse({"error": str(exc)}, status_code=400)


@router.get("/second-brain/api/events")
async def second_brain_events(request: Request, cursor: int = Query(0, ge=0)):
    if not get_current_user(request):
        return _unauthorized()
    header_cursor = request.headers.get("last-event-id", "").strip()
    if header_cursor.isdigit():
        cursor = max(cursor, int(header_cursor))

    async def stream():
        current = cursor
        heartbeat = 0
        initial = snapshot(client="web")
        current = max(current, int(initial["cursor"]))
        yield f"id: {current}\nevent: snapshot\ndata: {json.dumps({'cursor': current})}\n\n"
        while not await request.is_disconnected():
            changes = await asyncio.to_thread(changes_after, current, client="web")
            for change in changes:
                current = max(current, int(change["revision"]))
                yield f"id: {current}\nevent: feed\ndata: {json.dumps({'cursor': current})}\n\n"
            heartbeat += 1
            if heartbeat >= 15:
                heartbeat = 0
                yield ": heartbeat\n\n"
            await asyncio.sleep(1)

    return StreamingResponse(
        stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache, no-transform",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@router.post("/second-brain/mode", response_class=HTMLResponse)
async def set_mode(
    request: Request,
    modes: str = Form(..., max_length=80),
    duration_minutes: int = Form(120),
):
    user, redirect = require_user(request)
    if redirect:
        return HTMLResponse("", status_code=401)
    correlation_id = str(uuid.uuid4())
    try:
        parsed = [part for part in _MODE_SPLIT.split(modes) if part]
        get_second_brain_store().set_override(
            parsed,
            duration_minutes=duration_minutes,
            correlation_id=correlation_id,
        )
        _dispatch_reconcile(correlation_id)
    except ValueError as exc:
        return HTMLResponse(str(exc), status_code=400)
    return templates.TemplateResponse(
        request,
        "modules/second_brain/_shell.html",
        _view_context(request, user),
    )


@router.post("/second-brain/mode/auto", response_class=HTMLResponse)
async def set_auto_mode(request: Request):
    user, redirect = require_user(request)
    if redirect:
        return HTMLResponse("", status_code=401)
    correlation_id = str(uuid.uuid4())
    get_second_brain_store().clear_override()
    _dispatch_reconcile(correlation_id)
    return templates.TemplateResponse(
        request,
        "modules/second_brain/_shell.html",
        _view_context(request, user),
    )


@router.post("/second-brain/refresh", response_class=HTMLResponse)
async def refresh_second_brain(request: Request):
    user, redirect = require_user(request)
    if redirect:
        return HTMLResponse("", status_code=401)
    task_id = _dispatch_reconcile(str(uuid.uuid4()))
    return HTMLResponse(
        f'<p class="text-xs text-sky-300">Refresh queued · {task_id[:12]}</p>',
        headers={"HX-Trigger": "second-brain-refresh"},
    )


@router.post("/second-brain/settings", response_class=HTMLResponse)
async def update_settings(
    request: Request,
    telegram: str | None = Form(None),
    rainmeter: str | None = Form(None),
    cli: str | None = Form(None),
    hermes: str | None = Form(None),
):
    user, redirect = require_user(request)
    if redirect:
        return HTMLResponse("", status_code=401)
    get_second_brain_store().update_config(
        clients={
            "web": True,
            "telegram": telegram == "on",
            "rainmeter": rainmeter == "on",
            "cli": cli == "on",
        },
        hermes_enabled=hermes == "on",
    )
    return templates.TemplateResponse(
        request,
        "modules/second_brain/_shell.html",
        _view_context(request, user),
    )


@router.post("/second-brain/api/commands")
async def second_brain_command(request: Request):
    if not get_current_user(request):
        return _unauthorized()
    try:
        payload = await request.json()
    except (json.JSONDecodeError, ValueError):
        return JSONResponse({"error": "invalid JSON"}, status_code=400)
    command = str(payload.get("command") or "").strip()
    if not command or len(command) > 2_000:
        return JSONResponse({"error": "command must contain 1-2000 characters"}, status_code=400)
    correlation_id = str(uuid.uuid4())
    if command.casefold() == "/mode auto":
        get_second_brain_store().clear_override()
    elif command.casefold().startswith("/mode "):
        parts = command[6:].split(" for ", 1)
        modes = [part for part in _MODE_SPLIT.split(parts[0]) if part]
        duration = 120
        if len(parts) == 2:
            match = re.fullmatch(r"(\d{1,2})h", parts[1].strip().casefold())
            if not match:
                return JSONResponse({"error": "duration must look like 2h"}, status_code=400)
            duration = int(match.group(1)) * 60
        try:
            get_second_brain_store().set_override(modes, duration_minutes=duration, correlation_id=correlation_id)
        except ValueError as exc:
            return JSONResponse({"error": str(exc)}, status_code=400)
    else:
        from workflows.second_brain.models import ContextEvent

        get_second_brain_store().append_context(
            ContextEvent(
                source="frontend_command",
                event_type="text_command",
                payload={"text": command},
                correlation_id=correlation_id,
            )
        )
    task_id = _dispatch_reconcile(correlation_id)
    return JSONResponse({"accepted": True, "correlation_id": correlation_id, "task_id": task_id}, status_code=202)
