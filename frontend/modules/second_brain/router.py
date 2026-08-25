"""Authenticated page, commands, settings, snapshots, and SSE feed."""

from __future__ import annotations

import asyncio
import hmac
import json
import os
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


def _dispatch_reconcile(correlation_id: str, *, force: bool = True) -> str:
    return celery_client.dispatch(
        task_path="workflows.second_brain.tasks.reconcile.reconcile_second_brain",
        kwargs={"correlation_id": correlation_id, "force": force},
        queue="host",
    )


def _split_values(value: str) -> tuple[str, ...]:
    return tuple(part.strip() for part in re.split(r"[,\n]+", value or "") if part.strip())


def _available_manual_modes(store, requested) -> list[str]:
    available = [
        mode["mode_id"]
        for mode in store.list_modes()
        if mode.get("enabled", True) and not mode.get("archived", False)
    ]
    selected = [
        str(mode).strip().casefold()
        for mode in (requested or ())
        if str(mode).strip().casefold() in available
    ]
    if selected:
        return list(dict.fromkeys(selected))
    if "default" in available:
        return ["default"]
    if available:
        return [available[0]]
    raise ValueError("enable at least one category before using manual selection")


def _category_id(name: str, existing_ids: set[str]) -> str:
    """Create an immutable, human-readable category key from its initial name."""
    base = re.sub(r"[^a-z0-9]+", "-", name.strip().casefold()).strip("-")
    if not base or not base[0].isalpha():
        base = f"category-{base or 'new'}"
    base = base[:48].rstrip("-")
    candidate = base
    suffix = 2
    while candidate in existing_ids:
        marker = f"-{suffix}"
        candidate = f"{base[:48 - len(marker)].rstrip('-')}{marker}"
        suffix += 1
    return candidate


def _api_authenticated(request: Request) -> bool:
    if get_current_user(request):
        return True
    expected = os.environ.get("SECOND_BRAIN_API_TOKEN", "").strip()
    authorization = request.headers.get("authorization", "")
    supplied = authorization[7:].strip() if authorization.casefold().startswith("bearer ") else ""
    return bool(expected and supplied and hmac.compare_digest(expected, supplied))


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
    if not _api_authenticated(request):
        return _unauthorized()
    if client == "web" and not get_current_user(request):
        return JSONResponse({"error": "the API token is limited to redacted delivery clients"}, status_code=403)
    try:
        return JSONResponse(snapshot(client=client, limit=limit))
    except PermissionError as exc:
        return JSONResponse({"error": str(exc)}, status_code=403)
    except ValueError as exc:
        return JSONResponse({"error": str(exc)}, status_code=400)


@router.get("/second-brain/api/events")
async def second_brain_events(request: Request, cursor: int = Query(0, ge=0)):
    if not _api_authenticated(request):
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


@router.post("/second-brain/automatic")
async def update_automatic_feed(request: Request):
    if not get_current_user(request):
        return _unauthorized()
    payload = await request.json()
    enabled = bool(payload.get("enabled"))
    correlation_id = str(uuid.uuid4())
    store = get_second_brain_store()
    if enabled:
        store.clear_override()
    else:
        try:
            modes = _available_manual_modes(store, payload.get("modes"))
            store.set_override(
                modes,
                duration_minutes=int(payload.get("duration_minutes", 120)),
                correlation_id=correlation_id,
            )
        except (TypeError, ValueError) as exc:
            return JSONResponse({"error": str(exc)}, status_code=400)
    task_id = _dispatch_reconcile(correlation_id)
    return JSONResponse({"saved": True, "automatic_feed": enabled, "task_id": task_id})


@router.post("/second-brain/selection")
async def update_selection(request: Request):
    if not get_current_user(request):
        return _unauthorized()
    payload = await request.json()
    correlation_id = str(uuid.uuid4())
    try:
        store = get_second_brain_store()
        override = store.set_override(
            _available_manual_modes(store, payload.get("modes")),
            duration_minutes=int(payload.get("duration_minutes", 120)),
            correlation_id=correlation_id,
        )
    except (TypeError, ValueError) as exc:
        return JSONResponse({"error": str(exc)}, status_code=400)
    task_id = _dispatch_reconcile(correlation_id)
    return JSONResponse({"saved": True, "override": override, "task_id": task_id})


@router.post("/second-brain/delivery/{client}")
async def update_delivery(request: Request, client: str):
    if not get_current_user(request):
        return _unauthorized()
    if client not in {"telegram", "rainmeter", "cli"}:
        return JSONResponse({"error": "unsupported delivery client"}, status_code=400)
    payload = await request.json()
    enabled = bool(payload.get("enabled"))
    store = get_second_brain_store()
    config = store.get_config()
    clients = dict(config.get("clients") or {})
    clients[client] = enabled
    store.save_config({"clients": clients})
    delivery_task_id = ""
    if enabled and client == "telegram":
        delivery_task_id = celery_client.dispatch(
            task_path="workflows.second_brain.tasks.deliver.deliver_second_brain_telegram",
            kwargs={},
            queue="host",
        )
    elif enabled and client == "rainmeter":
        delivery_task_id = celery_client.dispatch(
            task_path="workflows.hud.tasks.second_brain.render_second_brain_rainmeter",
            kwargs={},
            queue="hud",
        )
    return JSONResponse({"saved": True, "client": client, "enabled": enabled, "task_id": delivery_task_id})


@router.post("/second-brain/categories")
async def save_category(
    request: Request,
    mode_id: str = Form(""),
    name: str = Form(...),
    color: str = Form("#38bdf8"),
    order: int = Form(0),
    enabled: str | None = Form(None),
    keywords: str = Form(""),
    calendar_categories: str = Form(""),
    operation_ids: str = Form(""),
    refresh_minutes: int = Form(15),
    client_eligibility: str = Form("web,telegram,rainmeter,cli"),
    fallback_start: str = Form(""),
    fallback_end: str = Form(""),
):
    if not get_current_user(request):
        return _unauthorized()
    from apps.google_apps.references.constants import ScheduleCategory
    from workflows.second_brain.models import ModeDefinition
    from workflows.second_brain.registry import OPERATIONS

    calendars = _split_values(calendar_categories)
    allowed_calendars = {value.value for value in ScheduleCategory}
    operations = _split_values(operation_ids)
    clients = _split_values(client_eligibility)
    if set(calendars) - allowed_calendars:
        return JSONResponse({"error": "unsupported calendar category"}, status_code=400)
    if set(operations) - set(OPERATIONS):
        return JSONResponse({"error": "operation is not eligible or registered"}, status_code=400)
    try:
        fallback_windows = ()
        if fallback_start or fallback_end:
            clock = r"(?:[01]\d|2[0-3]):[0-5]\d"
            if not (re.fullmatch(clock, fallback_start) and re.fullmatch(clock, fallback_end)):
                raise ValueError("fallback start and end must both use HH:MM")
            fallback_windows = ({"start": fallback_start, "end": fallback_end, "days": list(range(7))},)
        store = get_second_brain_store()
        if not mode_id.strip():
            mode_id = _category_id(
                name,
                {mode["mode_id"] for mode in store.list_modes(include_archived=True)},
            )
        config = store.save_mode(
            ModeDefinition(
                mode_id=mode_id,
                name=name,
                color=color,
                order=order,
                enabled=enabled == "on",
                keywords=_split_values(keywords),
                calendar_categories=calendars,
                operation_ids=operations,
                refresh_minutes=refresh_minutes,
                client_eligibility=clients,
                fallback_windows=fallback_windows,
            )
        )
    except ValueError as exc:
        return JSONResponse({"error": str(exc)}, status_code=400)
    _dispatch_reconcile(str(uuid.uuid4()))
    return JSONResponse({"saved": True, "version": config["version"], "mode_id": mode_id})


@router.post("/second-brain/categories/{mode_id}/archive")
async def archive_category(request: Request, mode_id: str):
    if not get_current_user(request):
        return _unauthorized()
    try:
        config = get_second_brain_store().archive_mode(mode_id)
    except ValueError as exc:
        return JSONResponse({"error": str(exc)}, status_code=400)
    _dispatch_reconcile(str(uuid.uuid4()))
    return JSONResponse({"saved": True, "version": config["version"]})


@router.post("/second-brain/agent-settings")
async def update_agent_settings(request: Request):
    if not get_current_user(request):
        return _unauthorized()
    payload = await request.json()
    try:
        retention = int(payload.get("chat_retention_hours", 8))
    except (TypeError, ValueError):
        return JSONResponse({"error": "chat retention must be a whole number of hours"}, status_code=400)
    config = get_second_brain_store().save_config(
        {"hermes_enabled": bool(payload.get("hermes_enabled")), "chat_retention_hours": retention}
    )
    return JSONResponse({"saved": True, "version": config["version"]})


@router.post("/second-brain/chat")
async def second_brain_chat(request: Request):
    if not get_current_user(request):
        return _unauthorized()
    payload = await request.json()
    question = str(payload.get("message") or "").strip()
    if not question or len(question) > 2_000:
        return JSONResponse({"error": "message must contain 1-2000 characters"}, status_code=400)
    correlation_id = str(uuid.uuid4())
    store = get_second_brain_store()
    store.append_chat(role="user", content=question, correlation_id=correlation_id)
    from workflows.second_brain.models import ContextEvent

    store.append_context(ContextEvent(source="second_brain_chat", event_type="text_command", payload={"text": question}, correlation_id=correlation_id))
    _dispatch_reconcile(correlation_id)

    async def stream():
        yield f"event: accepted\ndata: {json.dumps({'correlation_id': correlation_id})}\n\n"
        try:
            if not store.get_config().get("hermes_enabled"):
                answer = "I recorded that context and refreshed your briefing. Enable Hermes interpretation in settings for a conversational answer."
                citations = []
            else:
                from workflows.second_brain.hermes import chat_with_feed

                decision = store.latest_decision() or {}
                feed = store.feed_snapshot(client="web", modes=decision.get("effective_modes") or (), limit=30)["items"]
                result = await asyncio.to_thread(chat_with_feed, question=question, history=store.recent_chat(limit=20), feed_items=feed)
                answer, citations = result["answer"], result["citations"]
            store.append_chat(role="assistant", content=answer, correlation_id=correlation_id, citations=citations)
            yield f"event: answer\ndata: {json.dumps({'content': answer, 'citations': citations})}\n\n"
        except Exception as exc:
            yield f"event: error\ndata: {json.dumps({'error': type(exc).__name__})}\n\n"

    return StreamingResponse(stream(), media_type="text/event-stream", headers={"Cache-Control": "no-store"})


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
