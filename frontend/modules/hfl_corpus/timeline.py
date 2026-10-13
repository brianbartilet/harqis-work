"""Owner-only agenda commands and stable links to unprotected HFL evidence."""
from __future__ import annotations

import asyncio
import json
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
from workflows.hfl.timeline_store import FollowUpConflict, FollowUpStore, store_path, priority_key


class TimelineRoute(APIRoute):
    def get_route_handler(self):
        handler = super().get_route_handler()
        async def route(request):
            if request.url.path.startswith('/hfl-corpus/') and '/ideas/share-context' in request.url.path:
                raise HTTPException(403, 'Sharing context is available only to the authenticated sharing service.')
            if request.url.path.startswith('/hfl-corpus/'):
                owner(request)
                if request.method == 'PATCH' and re.fullmatch(r'/hfl-corpus/timeline/items/[^/]+', request.url.path):
                    from modules.integrations.service import guard_status
                    await asyncio.to_thread(guard_status, get_current_user(request), request.url.path.rsplit('/', 1)[-1], await request.json())
                settings = get_settings()
                if settings.hfl_corpus_api_url and os.getenv('HFL_TIMELINE_LOCAL_PREVIEW') != '1':
                    target = settings.hfl_corpus_api_url.rstrip('/') + '/api/hfl/timeline' + request.url.path.split('/timeline', 1)[1]
                    try:
                        async with httpx.AsyncClient(timeout=45) as client:
                            response = await client.request(request.method, target, params=request.query_params, content=await request.body(), headers={'Authorization': 'Bearer '+settings.hfl_corpus_api_token, 'Content-Type': 'application/json'})
                        if response.status_code == 303:
                            return RedirectResponse(response.headers['location'], status_code=303)
                        data = response.json()
                        if response.is_success and request.url.path.endswith('/history'):
                            data = render_history(data)
                        return JSONResponse(data, status_code=response.status_code)
                    except (httpx.HTTPError, ValueError):
                        raise HTTPException(502, 'The canonical timeline is unavailable.') from None
            return await handler(request)
        return route


router = APIRouter(prefix="/timeline", route_class=TimelineRoute)


def render_history(data):
    from services.markdown import render_markdown
    for row in data.get('history', []):
        row['item']['completion_note_html'] = str(render_markdown(row['item'].get('completion_note', '')))
    return data


ENTRY_ID = re.compile(r"(?im)^\s*(?:\*\*)?Entry ID:(?:\*\*)?\s*(hfl-[a-zA-Z0-9_-]+)\s*$")


def entry_guid(entry):
    match = ENTRY_ID.search(entry.text)
    return match.group(1) if match else ""


def entry_evidence_id(text):
    """Resolve legacy evidence by content, without changing the corpus or graph IDs."""
    import hashlib
    match = ENTRY_ID.search(text)
    if match:
        return match.group(1)
    normalized = text.replace('\r\n', '\n').strip()
    return 'hfl-legacy-evidence-' + hashlib.sha256(normalized.encode('utf-8')).hexdigest()


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
            if entry_evidence_id(entry.text) == guid and not corpus.is_secret_entry(entry, tags):
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
async def followup_list(request: Request, closed: bool = False, offset: int = 0, include_closed: bool = False, recent_dismissed: bool = False):
    owner(request)
    today = datetime.now(ZoneInfo("Asia/Singapore")).date().isoformat()
    canonical = store()
    items = (canonical.list() + canonical.list(closed=True)) if include_closed else canonical.list(closed=closed)
    from modules.hfl_corpus.action_scope import filter_actions
    items = await filter_actions(request, items, canonical, recent_dismissed=recent_dismissed)
    positions = canonical.board_order()
    for item in items:
        item['board_position'] = positions.get(item['id'], 2147483647)
        is_closed = item['status'] in {'done', 'dismissed'}
        due, review = item["due_date"], item["review_date"]
        item["overdue"] = bool(due and due < today and not is_closed)
        item["group"] = "Completed" if item["status"] == "done" else "Dismissed" if is_closed else (
            "Overdue" if item["overdue"] else "Today" if (due and due == today) or (review and review <= today) else
            "Upcoming" if due or review else "Unscheduled")
    items.sort(key=priority_key)
    if offset < 0:
        raise HTTPException(422, 'Offset cannot be negative.')
    return {"items": items[offset:offset + 500], "total": len(items), "today": today, "timezone": "Asia/Singapore"}


@router.put('/items/order')
async def followup_board_order(request: Request):
    owner(request)
    raw = await body(request)
    try:
        store().reorder_board(raw.get('status'), raw.get('items'))
    except FollowUpConflict as exc:
        raise HTTPException(409, str(exc)) from None
    except (ValueError, TypeError) as exc:
        raise HTTPException(400, str(exc)) from None
    return {'saved': True}


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
        for field in ('matrix', 'matrix_confidence', 'matrix_reason'):
            raw.setdefault(field, suggestion.get(field, ''))
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


@router.post('/items/{followup_id}/checklist-action')
async def checklist_action(request: Request, followup_id: str):
    actor = owner(request)
    raw = await body(request)
    canonical = store()
    try:
        request_id = str(uuid.UUID(raw.get('request_id', '')))
        checklist_id, item_id = raw.get('checklist_id'), raw.get('item_id')
        if not isinstance(checklist_id, str) or not isinstance(item_id, str):
            raise ValueError('Choose a checklist item.')
        fields = raw.get('item')
        if not isinstance(fields, dict):
            raise ValueError('Invalid action draft.')
        # Scope retries to the source item; creation and completion commit together.
        request_id = str(uuid.uuid5(uuid.UUID(request_id), json.dumps([followup_id, checklist_id, item_id])))
        with canonical.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            row = db.execute('SELECT payload FROM followups WHERE id=?', (followup_id,)).fetchone()
            if not row:
                raise KeyError(followup_id)
            parent = json.loads(row['payload'])
            task = next((task for checklist in parent.get('checklists', []) if checklist['id'] == checklist_id
                         for task in checklist['items'] if task['id'] == item_id), None)
            if task is None:
                raise FollowUpConflict('The checklist item changed or was removed. Reopen the action.')
            action, duplicate = canonical.create({**fields, 'request_id': request_id, 'agent_enabled': False},
                                                  actor=actor, source=parent.get('source'), connection=db)
            if not duplicate:
                task['done'] = True
                parent = canonical.update(followup_id, {'version': raw.get('version'), 'checklists': parent['checklists']},
                                          actor=actor, connection=db)
        return {'item': action, 'parent': parent, 'duplicate': duplicate}
    except KeyError:
        raise HTTPException(404, 'Action not found.') from None
    except FollowUpConflict as exc:
        raise HTTPException(409, str(exc)) from None
    except (ValueError, TypeError) as exc:
        raise HTTPException(400, str(exc)) from None


@router.patch("/items/{followup_id}")
async def followup_update(request: Request, followup_id: str, background_tasks: BackgroundTasks):
    user = owner(request)
    raw = await body(request)
    agent_actor = raw.pop('_agent_actor', None)
    if agent_actor is not None:
        if not request.url.path.startswith('/api/hfl/') or not isinstance(agent_actor, str) or not re.fullmatch(r'agent:hermes:[a-f0-9]{32}:(active|in_progress|done|incomplete)', agent_actor):
            raise HTTPException(400, 'Invalid agent attribution.')
        user = agent_actor
    try:
        item = await asyncio.to_thread(store().update, followup_id, raw, actor=user)
    except KeyError:
        raise HTTPException(404, "Follow-up not found.") from None
    except FollowUpConflict as exc:
        raise HTTPException(409, str(exc)) from None
    except (ValueError, TypeError) as exc:
        raise HTTPException(400, str(exc)) from None
    receipts = await asyncio.to_thread(store().receipts, pending_only=True)
    if any(r['followup_id'] == item['id'] and r['version'] == item['version'] for r in receipts):
        background_tasks.add_task(write_completion, item['id'], item['version'], store=store())
    return {"item": item}


@router.get("/items/{followup_id}")
async def followup_get(request: Request, followup_id: str):
    owner(request)
    try:
        return {'item': store().get(followup_id)}
    except KeyError:
        raise HTTPException(404, 'Follow-up not found.') from None


@router.get("/items/{followup_id}/history")
async def followup_history(request: Request, followup_id: str):
    owner(request)
    try:
        return render_history({"history": store().history(followup_id)})
    except KeyError:
        raise HTTPException(404, "Follow-up not found.") from None


def item_events(item, canonical):
    events = []
    if (item.get('source') or {}).get('date'):
        events.append({'date': item['source']['date'], 'kind': 'source'})
    if item['status'] != 'dismissed':
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
    day_statuses = {}
    from modules.hfl_corpus.action_scope import filter_actions
    for item in await filter_actions(request, canonical.list() + canonical.list(closed=True), canonical):
        for event in item_events(item, canonical):
            day = days.setdefault(event['date'], {'planned': [], 'actions': []})
            # Source and status-history days expose these actions too. Use their
            # current state so an old completion cannot hide an incomplete action.
            # A removed schedule alone must not retain a deadline dot.
            if item['status'] != 'dismissed' and event['kind'] != 'previous-plan':
                day_statuses.setdefault(event['date'], set()).add(item['status'])
            key = 'planned' if event['kind'] == 'planned' else 'actions'
            if item['id'] not in day[key]:
                day[key].append(item['id'])
    for day, value in days.items():
        statuses = day_statuses.get(day, set())
        value['dot_status'] = ('incomplete' if 'incomplete' in statuses else 'open' if statuses & {'open', 'active'} else
                               'in_progress' if 'in_progress' in statuses else
                               'done' if statuses == {'done'} else None)
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
    from modules.hfl_corpus.action_scope import filter_actions
    for item in await filter_actions(request, canonical.list() + canonical.list(closed=True), canonical):
        events = [event for event in item_events(item, canonical) if start <= event['date'] <= end]
        if events:
            items.append({**item, 'events': events})
    items.sort(key=priority_key)
    return {'suggestions': canonical.suggestions(start, end), 'items': items, 'run': canonical.run_for(start, end), 'receipts': canonical.receipts()}


@router.post('/suggestions/{sid}/dismiss')
async def dismiss_suggestion(request: Request, sid: str):
    actor = owner(request)
    from modules.hfl_corpus.ideas_api import require_idea, call, store as ideas_store
    item = require_idea(sid)
    call(ideas_store().save_idea, {'version': item['version'], 'status': 'dismissed'}, actor, sid)
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
