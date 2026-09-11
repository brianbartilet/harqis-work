"""Owner-only agenda commands and stable links to unprotected HFL evidence."""
from __future__ import annotations

import asyncio
import re
import os
import uuid
import httpx
from datetime import datetime
from urllib.parse import quote
from zoneinfo import ZoneInfo

from fastapi import APIRouter, BackgroundTasks, HTTPException, Request
from fastapi.responses import JSONResponse, RedirectResponse

from auth import get_current_user
from fastapi.routing import APIRoute
from config import get_settings
from workflows.hfl.timeline import period, explore_period, write_completion
from workflows.hfl.timeline_store import FollowUpConflict, FollowUpStore, store_path


class TimelineRoute(APIRoute):
    def get_route_handler(self):
        handler = super().get_route_handler()
        async def route(request):
            if request.url.path.startswith('/hfl-corpus/'):
                owner(request)
                settings = get_settings()
                if settings.hfl_corpus_api_url and os.getenv('HFL_TIMELINE_LOCAL_PREVIEW') != '1':
                    target = settings.hfl_corpus_api_url.rstrip('/') + '/api/hfl/timeline' + request.url.path.split('/timeline', 1)[1]
                    try:
                        async with httpx.AsyncClient(timeout=45) as client:
                            response = await client.request(request.method, target, params=request.query_params, content=await request.body(), headers={'Authorization': 'Bearer '+settings.hfl_corpus_api_token, 'Content-Type': 'application/json'})
                        if response.status_code == 303:
                            return RedirectResponse(response.headers['location'], status_code=303)
                        return JSONResponse(response.json(), status_code=response.status_code)
                    except (httpx.HTTPError, ValueError):
                        raise HTTPException(502, 'The canonical timeline is unavailable.') from None
            return await handler(request)
        return route


router = APIRouter(prefix="/timeline", route_class=TimelineRoute)
ENTRY_ID = re.compile(r"(?im)^\s*(?:\*\*)?Entry ID:(?:\*\*)?\s*(hfl-[a-zA-Z0-9_-]+)\s*$")


def entry_guid(entry):
    match = ENTRY_ID.search(entry.text)
    return match.group(1) if match else ""


def store():
    return FollowUpStore(store_path())


def owner(request):
    user = "owner-api" if request.url.path.startswith("/api/hfl/") else get_current_user(request)
    if not user:
        raise HTTPException(401, "Sign in to manage follow-ups.")
    return user


async def evidence(path, guid):
    from modules.hfl_corpus import router as corpus
    if not isinstance(path, str) or not path.endswith(".md") or len(path) > 1000 or ".." in path.split("/") or path.startswith(("/", "\\")) or "\\" in path:
        raise HTTPException(400, "Choose a corpus document.")
    if not isinstance(guid, str) or not re.fullmatch(r"hfl-[a-zA-Z0-9_-]+", guid):
        raise HTTPException(400, "A stable HFL entry ID is required.")
    tags = corpus.normalize_secret_tags(corpus.get_profile_store().get().secret_tags)
    if corpus._uses_remote_corpus():
        try:
            document, _ = await asyncio.to_thread(corpus.RemoteCorpusClient.from_settings().document, path, include_secrets=False, secret_tags=tags)
        except corpus.RemoteCorpusError:
            raise HTTPException(502, "HFL is unavailable. Try again shortly.") from None
    else:
        document = corpus.corpus_index.get(path)
    if document:
        for entry in document.entries:
            if entry_guid(entry) == guid and not corpus.is_secret_entry(entry, tags):
                return entry
    raise HTTPException(404, "The evidence entry is unavailable or protected.")


async def body(request):
    try:
        data = await request.json()
    except ValueError:
        raise HTTPException(400, "Invalid JSON.") from None
    if not isinstance(data, dict):
        raise HTTPException(400, "Expected a JSON object.")
    return data


@router.get("/source")
async def followup_source(request: Request, path: str, entry_id: str):
    owner(request)
    entry = await evidence(path, entry_id)
    return {"path": path, "entry_id": entry_id, "title": entry.moment or entry.header, "date": entry.header[:10]}


@router.get("/evidence")
async def followup_evidence(request: Request, path: str, entry_id: str):
    owner(request)
    entry = await evidence(path, entry_id)
    return RedirectResponse(f"/hfl-corpus/document/{quote(path, safe='/')}#{quote(entry.anchor)}", status_code=303)


@router.get("/items")
async def followup_list(request: Request, closed: bool = False):
    owner(request)
    today = datetime.now(ZoneInfo("Asia/Singapore")).date().isoformat()
    items = store().list(closed=closed)
    for item in items:
        due, review = item["due_date"], item["review_date"]
        item["overdue"] = bool(due and due < today and not closed)
        item["group"] = "Completed" if item["status"] == "done" else "Dismissed" if closed else (
            "Overdue" if item["overdue"] else "Today" if (due and due == today) or (review and review <= today) else
            "Upcoming" if due or review else "Unscheduled")
    order = {"Overdue": 0, "Today": 1, "Upcoming": 2, "Unscheduled": 3, "Completed": 4, "Dismissed": 5}
    if not closed:
        items.sort(key=lambda item: (order[item["group"]], min(filter(None, [item["due_date"], item["review_date"]]), default="9999"), item["created_at"]))
    return {"items": items[:500], "total": len(items), "today": today, "timezone": "Asia/Singapore"}


@router.post("/items")
async def followup_create(request: Request):
    user = owner(request)
    raw = await body(request)
    sid = raw.pop("suggestion_id", None)
    if sid:
        try:
            suggestion = store().suggestion(sid)
        except KeyError:
            raise HTTPException(404, 'Suggestion not found.') from None
        if suggestion['status'] == 'adopted':
            return {'item': store().get(suggestion['followup_id']), 'duplicate': True}
        if suggestion['status'] == 'dismissed':
            raise HTTPException(409, 'This suggestion was dismissed.')
        raw['source'] = suggestion['source']
        raw['request_id'] = str(uuid.uuid5(uuid.NAMESPACE_URL, sid))
    source = raw.pop("source", None)
    if source is not None:
        if not isinstance(source, dict):
            raise HTTPException(400, "Invalid evidence link.")
        entry = await evidence(source.get("path"), source.get("entry_id"))
        source = {"path": source["path"], "entry_id": source["entry_id"], "title": entry.moment or entry.header, "date": entry.header[:10]}
    try:
        item, duplicate = store().create(raw, actor=user, source=source, suggestion_id=sid)
    except FollowUpConflict as exc:
        raise HTTPException(409, str(exc)) from None
    except (ValueError, TypeError) as exc:
        raise HTTPException(400, str(exc)) from None
    return JSONResponse({"item": item, "duplicate": duplicate}, status_code=200 if duplicate else 201)


@router.patch("/items/{followup_id}")
async def followup_update(request: Request, followup_id: str, background_tasks: BackgroundTasks):
    user = owner(request)
    raw = await body(request)
    try:
        item = store().update(followup_id, raw, actor=user)
    except KeyError:
        raise HTTPException(404, "Follow-up not found.") from None
    except FollowUpConflict as exc:
        raise HTTPException(409, str(exc)) from None
    except (ValueError, TypeError) as exc:
        raise HTTPException(400, str(exc)) from None
    if any(r['followup_id'] == item['id'] and r['version'] == item['version'] for r in store().receipts(pending_only=True)):
        background_tasks.add_task(write_completion, item['id'], item['version'], store=store())
    return {"item": item}


@router.get("/items/{followup_id}/history")
async def followup_history(request: Request, followup_id: str):
    owner(request)
    try:
        return {"history": store().history(followup_id)}
    except KeyError:
        raise HTTPException(404, "Follow-up not found.") from None


def item_events(item, canonical):
    events = []
    if (item.get('source') or {}).get('date'):
        events.append({'date': item['source']['date'], 'kind': 'source'})
    if item['status'] not in {'done', 'dismissed'}:
        for field in ('review_date', 'due_date'):
            if item[field]:
                events.append({'date': item[field], 'kind': 'planned'})
    for row in canonical.history(item['id']):
        for field in ('review_date', 'due_date'):
            old_date = row['item'][field]
            if old_date and not any(event['date'] == old_date and event['kind'] in {'planned', 'previous-plan'} for event in events):
                events.append({'date': old_date, 'kind': 'previous-plan', 'version': row['item']['version']})
        events.append({'date': datetime.fromisoformat(row['changed_at']).astimezone(ZoneInfo('Asia/Singapore')).date().isoformat(), 'kind': row['item']['status'], 'version': row['item']['version']})
    return events


@router.get('/markers')
async def markers(request: Request):
    owner(request)
    canonical = store()
    days = {}
    for item in canonical.list() + canonical.list(closed=True):
        for event in item_events(item, canonical):
            day = days.setdefault(event['date'], {'planned': [], 'actions': []})
            key = 'planned' if event['kind'] == 'planned' else 'actions'
            if item['id'] not in day[key]:
                day[key].append(item['id'])
    return {'days': days}


@router.get('/period')
async def timeline_period(request: Request, start: str, end: str):
    owner(request)
    try:
        period(start, end)
    except (ValueError, TypeError):
        raise HTTPException(400, 'Choose a valid period of 1–31 days.') from None
    canonical = store()
    items = []
    for item in canonical.list() + canonical.list(closed=True):
        events = [event for event in item_events(item, canonical) if start <= event['date'] <= end]
        if events:
            items.append({**item, 'events': events})
    return {'suggestions': canonical.suggestions(start, end), 'items': items, 'run': canonical.run_for(start, end), 'receipts': canonical.receipts()}


@router.post('/suggestions/{sid}/dismiss')
async def dismiss_suggestion(request: Request, sid: str):
    owner(request)
    try:
        item = store().suggestion(sid)
    except KeyError:
        raise HTTPException(404, 'Suggestion not found.') from None
    if item['status'] == 'adopted':
        raise HTTPException(409, 'Update the adopted action instead.')
    store().mark_suggestion(sid, 'dismissed')
    return {'status': 'dismissed'}


@router.post('/explore', status_code=202)
async def explore(request: Request, background_tasks: BackgroundTasks):
    owner(request)
    raw = await body(request)
    start, end = raw.get('start'), raw.get('end')
    try:
        _, last = period(start, end)
        if last > datetime.now(ZoneInfo('Asia/Singapore')).date():
            raise ValueError()
    except (ValueError, TypeError):
        raise HTTPException(400, 'Choose 1–31 days ending today or earlier.') from None
    canonical = store()
    run_id = canonical.claim_period(start, end, force=True)
    if run_id:
        if os.getenv('HFL_TIMELINE_LOCAL_PREVIEW') == '1':
            background_tasks.add_task(explore_period, start, end, run_id=run_id, store=canonical)
        else:
            try:
                from workflows.hfl.tasks.timeline_suggestions import generate_timeline_suggestions
                from workflows.queues import WorkflowQueue
                generate_timeline_suggestions.apply_async(kwargs={'start': start, 'end': end, 'run_id': run_id}, queue=WorkflowQueue.HOST)
            except Exception:
                canonical.finish_period(start, end, run_id, {'message': 'Could not queue exploration. Retry when the worker is available.'}, state='failed')
                raise HTTPException(503, 'Could not queue exploration.') from None
    return {'run': canonical.run_for(start, end)}
