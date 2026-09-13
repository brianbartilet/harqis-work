"""Routes for browsing, searching, and adding entries to the HFL corpus."""

import asyncio
import base64
import html
import json
import logging
import math
import re
from dataclasses import replace
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any
from urllib.parse import quote, urlencode

from fastapi import APIRouter, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import (
    FileResponse,
    HTMLResponse,
    JSONResponse,
    Response,
    StreamingResponse,
)
from markupsafe import Markup
from pydantic import BaseModel, ValidationError

from config import get_settings
from modules.hfl_corpus.corpus import (
    CorpusPage,
    activity_calendar_years,
    activity_counts,
    activity_day_entries,
    build_tree,
    corpus_index,
    dated_document_paths,
    find_tree_node,
    format_hfl_markdown,
    paginate_documents,
    parse_search_query,
    normalize_source,
    resolve_corpus_root,
    search_documents,
    shallow_tree,
)
from services.markdown import render_markdown
from modules.hfl_corpus.remote import RemoteCorpusClient, RemoteCorpusError
from modules.hfl_corpus.entry_create import (
    CreateEntryRequest,
    persist_manual_entry,
    persist_manual_entry_with_uploads,
    preview_manual_entry,
)
from modules.hfl_corpus.document_edit import (
    DocumentConflictError,
    UpdateDocumentRequest,
    update_document_text,
)
from modules.hfl_corpus.entry_enrichment import enrich_manual_entry
from modules.hfl_corpus.secrets import (
    document_has_secrets,
    filter_documents,
    is_secret_entry,
    normalize_secret_tags,
    pin_rate_limited,
    secrets_unlocked,
    set_unlocked_cookie,
    verify_owner_pin,
)
from modules.hfl_corpus.memory_pins import get_memory_pin_store
from modules.hfl_corpus.view import corpus_view_cache
from modules.profile.store import get_profile_store
from modules.hfl_shares.security import make_csrf_token, verify_csrf_token
from modules.hfl_shares.viewer import (
    classify_preview,
    read_preview_text,
    thumbnail_path,
)
from services.safe_paths import (
    allowed_reference_roots,
    load_download_token,
    resolve_reference,
)
from web import page_context, require_user, templates


router = APIRouter(prefix="/hfl-corpus")
_H2 = re.compile(r"<h2(?:\s+[^>]*)?>(.*?)</h2>", re.DOTALL)
_log = logging.getLogger(__name__)


def _add_calendar_years(value: date, years: int) -> date:
    """Return the same calendar date in a later year, clamping leap day."""
    try:
        return value.replace(year=value.year + years)
    except ValueError:
        return value.replace(year=value.year + years, day=28)


class SecretPinRequest(BaseModel):
    pin: str


class MemoryPinRequest(BaseModel):
    csrf: str
    action: str
    category_id: int | None = None
    range_id: int | None = None
    name: str = ""
    color: str = ""
    start_date: str = ""
    end_date: str = ""
    note: str = ""
    title: str = ""
    prompt: str = ""
    execution_hour: int = 0
    agent_enabled: bool | None = None
    instructions: str = ""
    event_key: str = ""
    output: str = ""
    agent: str = ""
    model: str = ""
    status: str = "completed"
    system_prompt: str | None = None
    before_id: int = 0


@router.post("/memory-pins")
async def hfl_memory_pins(request: Request, payload: MemoryPinRequest):
    user, redirect = require_user(request)
    if redirect:
        return JSONResponse({"detail": "Authentication required"}, status_code=401)
    if not verify_csrf_token(payload.csrf, user):
        return JSONResponse({"detail": "Invalid form token."}, status_code=403)
    if payload.action == "preview_prompt":
        if len(payload.prompt) > 20000:
            return JSONResponse({"detail": "Use 20,000 characters or fewer."}, status_code=422)
        return JSONResponse({"html": str(render_markdown(payload.prompt))})
    store = get_memory_pin_store()
    try:
        if payload.action == "save_category":
            store.save_category(
                category_id=payload.category_id, name=payload.name, color=payload.color, instructions=payload.instructions
            )
        elif payload.action in {"delete_category", "archive_category", "restore_category"} and payload.category_id:
            store.archive_category(payload.category_id, restore=payload.action == "restore_category")
        elif payload.action == "agent_history" and payload.category_id:
            events = store.agent_history(payload.category_id, before_id=payload.before_id)
            for event in events:
                event['output_html'] = str(render_markdown(event['output']))
            return JSONResponse({"events": events})
        elif payload.action == "record_agent_event" and payload.category_id and payload.range_id:
            event_id = store.record_agent_event(category_id=payload.category_id, range_id=payload.range_id,
                event_key=payload.event_key, output=payload.output, agent=payload.agent,
                model=payload.model, status=payload.status, system_prompt=payload.system_prompt)
            return JSONResponse({"event_id": event_id})
        elif payload.action == "save_range":
            if not payload.category_id:
                raise ValueError("Choose a category.")
            try:
                range_start = date.fromisoformat(payload.start_date)
                range_end = date.fromisoformat(payload.end_date)
            except ValueError as exc:
                raise ValueError("Choose valid start and end dates.") from exc
            range_start, range_end = sorted((range_start, range_end))
            profile = get_profile_store().get()
            profile_birthdate = date.fromisoformat(profile.birthdate) if profile.birthdate else None
            if profile_birthdate and range_start < profile_birthdate:
                raise ValueError("Pinned dates cannot be earlier than your birthdate.")
            max_pin_date = _add_calendar_years(date.today(), 5)
            if range_end > max_pin_date:
                raise ValueError(
                    f"Pinned dates cannot be later than {max_pin_date.isoformat()}."
                )
            store.save_range(
                range_id=payload.range_id,
                category_id=payload.category_id,
                start_date=payload.start_date,
                end_date=payload.end_date,
                note=payload.note,
                title=payload.title,
                prompt=payload.prompt,
                execution_hour=payload.execution_hour,
                agent_enabled=payload.agent_enabled,
            )
            if payload.range_id and payload.agent_enabled is not None:
                from modules.hfl_corpus.agent_bridge import bridge_store
                bridge = bridge_store()
                sub = next((s for s in bridge.subscriptions() if s['source_key'] == f'pin:{payload.range_id}'), None)
                if sub:
                    cadence = (sub['cadence'] if sub['cadence'] != 'off' else 'daily') if payload.agent_enabled else 'off'
                    bridge.subscribe('pin', str(payload.range_id), cadence, True)
        elif payload.action == "delete_range" and payload.range_id:
            store.delete_range(payload.range_id)
        else:
            raise ValueError("Choose a valid Memory Signal action.")
    except ValueError as exc:
        return JSONResponse({"detail": str(exc)}, status_code=422)
    return JSONResponse(store.snapshot())


@router.post("/secrets/unlock")
async def hfl_secrets_unlock(request: Request, payload: SecretPinRequest):
    user, redirect = require_user(request)
    if redirect:
        return JSONResponse({"detail": "Authentication required"}, status_code=401)
    profile = get_profile_store().get()
    if not profile.secret_pin_hash:
        return JSONResponse(
            {"detail": "Set a secrets PIN in Profile Settings first."}, status_code=409
        )
    if pin_rate_limited(request, user):
        return JSONResponse(
            {"detail": "Too many incorrect attempts. Try again in 15 minutes."},
            status_code=429,
        )
    if not verify_owner_pin(request, user, payload.pin, profile):
        return JSONResponse({"detail": "Incorrect PIN."}, status_code=403)
    response = JSONResponse({"unlocked": True})
    set_unlocked_cookie(response, profile)
    return response


def _display_entry_header(header: str) -> str:
    """Format timestamp-only headings for display, preserving source wall time."""
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}[ T]\d{2}:\d{2}(?::\d{2}(?:\.\d+)?)?(?:Z|[+-]\d{2}:\d{2})?", header):
        return header
    try:
        when = datetime.fromisoformat(header.replace("Z", "+00:00"))
    except ValueError:
        return header
    label = when.strftime("%a %b %d %Y %I:%M %p")
    if when.tzinfo is not None:
        label += " " + when.tzname()
    return label


def _anchor_rendered_entries(rendered: Markup, document) -> Markup:
    from urllib.parse import urlencode
    from modules.hfl_corpus.timeline import entry_guid

    entries = iter(document.entries)
    protected_tags = normalize_secret_tags(get_profile_store().get().secret_tags)

    def replace(match: re.Match) -> str:
        entry = next(entries, None)
        if entry is None:
            return match.group(0)
        action = ""
        guid = entry_guid(entry)
        if guid and not is_secret_entry(entry, protected_tags):
            query = urlencode({"source_path": document.relative_path, "source_entry": guid})
            action = (f'<a class="corpus-followup-action" href="/hfl-corpus?{html.escape(query, quote=True)}" '
                      f'aria-describedby="{html.escape(entry.anchor, quote=True)}" '
                      'aria-label="Create a follow-up from this HFL entry">Make actionable ↗</a>')
        header = _display_entry_header(match.group(1))
        heading = f'<h2 id="{html.escape(entry.anchor, quote=True)}" class="scroll-mt-40">{header}</h2>'
        return f'<div class="corpus-entry-header">{heading}{action}</div>'

    return Markup(_H2.sub(replace, str(rendered)))


def _uses_remote_corpus() -> bool:
    return bool(get_settings().hfl_corpus_api_url.strip())


@router.get("/activity-year/{activity_year}")
async def hfl_activity_year(
    request: Request,
    activity_year: int,
    q: str = "",
    source: str = "",
    show_secrets: bool = False,
):
    user, redirect = require_user(request)
    if redirect:
        return JSONResponse({"detail": "Authentication required"}, status_code=401)
    profile = get_profile_store().get()
    try:
        birth_year = date.fromisoformat(profile.birthdate).year if profile.birthdate else None
    except ValueError:
        birth_year = None
    today = date.today()
    max_pin_date = _add_calendar_years(today, 5)
    first_year = birth_year or today.year - 19
    if activity_year < first_year or activity_year > max_pin_date.year:
        return JSONResponse({"detail": "Year is outside the Memory Signal."}, status_code=404)
    if activity_year > today.year:
        return JSONResponse({"year": activity_year, "counts": {}, "documents": {}})

    protected_tags = normalize_secret_tags(profile.secret_tags)
    include_secrets = bool(show_secrets and secrets_unlocked(request, profile))
    try:
        if _uses_remote_corpus():
            remote = await asyncio.to_thread(
                RemoteCorpusClient.from_settings().index,
                params={
                    "q": q,
                    "source": source,
                    "page": "1",
                    "page_size": "1",
                    "compact": "true",
                    "include_secrets": str(include_secrets).lower(),
                    "secret_tags": ",".join(protected_tags),
                    "activity_year": str(activity_year),
                },
            )
            activity = remote["activity"]
            counts = dict(activity.get("counts") or {})
            document_paths = dict(activity.get("documents") or {})
        else:
            view = corpus_view_cache.get(
                corpus_index.documents(),
                include_secrets=include_secrets,
                secret_tags=protected_tags,
            )
            selected_source = normalize_source(source, view.sources)
            counts = activity_counts(
                view.documents,
                year=activity_year,
                query=q,
                source=selected_source,
            )
            document_paths = dated_document_paths(view.documents)
    except RemoteCorpusError as exc:
        return JSONResponse({"detail": str(exc)}, status_code=503)

    prefix = f"{activity_year}-"
    return JSONResponse(
        {
            "year": activity_year,
            "counts": {key: value for key, value in counts.items() if key.startswith(prefix)},
            "documents": {
                key: value for key, value in document_paths.items() if key.startswith(prefix)
            },
        }
    )


def _reference_token(reference) -> str:
    href = reference.href or ""
    return href.rsplit("/", 2)[-2] if href.endswith("/download") else ""


def _with_reference_preview(reference):
    if reference.kind != "download" or not reference.href:
        return reference
    token = _reference_token(reference)
    if not token:
        return reference
    path = load_download_token(
        token,
        allowed_reference_roots(resolve_corpus_root()),
    )
    preview = classify_preview(path) if path else None
    if not preview:
        return reference
    base_url = reference.href.removesuffix("/download")
    return replace(
        reference,
        preview_kind=preview.kind,
        preview_url=f"{base_url}/preview",
        media_url=f"{base_url}/media",
        thumbnail_url=(
            f"{base_url}/thumbnail"
            if preview.kind in {"image", "video"}
            else ""
        ),
    )


def _document_tag_counts(document) -> tuple[tuple[str, int], ...]:
    counts = dict(document.tag_counts)
    for tag in document.tags:
        counts.setdefault(tag, len(document.matching_entries(tag)))
    return tuple(sorted(counts.items(), key=lambda item: (-item[1], item[0])))


def _document_source_options(document) -> tuple[dict[str, Any], ...]:
    sources: dict[str, dict[str, Any]] = {}
    for entry in document.entries:
        source = entry.source.strip()
        if not source:
            continue
        option = sources.setdefault(
            source.casefold(),
            {"source": source, "anchors": []},
        )
        option["anchors"].append(entry.anchor)
    return tuple(
        sorted(
            (
                {
                    "source": option["source"],
                    "count": len(option["anchors"]),
                    "anchors": tuple(option["anchors"]),
                }
                for option in sources.values()
            ),
            key=lambda option: (
                -option["count"],
                str(option["source"]).casefold(),
            ),
        )
    )


def _preview_path(token: str):
    path = load_download_token(
        token,
        allowed_reference_roots(resolve_corpus_root()),
    )
    if not path:
        raise HTTPException(status_code=404, detail="Reference unavailable.")
    preview = classify_preview(path)
    if not preview:
        raise HTTPException(
            status_code=415,
            detail="This file is not available for inline preview.",
        )
    return path, preview


def _preview_fragment(path: Path, preview) -> HTMLResponse:
    if preview.kind in {"image", "video"}:
        return HTMLResponse("", status_code=204, headers={"Cache-Control": "no-store"})
    try:
        source = read_preview_text(path)
    except (OSError, UnicodeDecodeError, ValueError):
        raise HTTPException(
            status_code=422,
            detail="This text file could not be safely displayed.",
        ) from None
    content = (
        f'<div class="viewer-document markdown-body">{render_markdown(source)}</div>'
        if preview.kind == "markdown"
        else (
            '<pre class="viewer-document viewer-plain-text">'
            f"{html.escape(source)}"
            "</pre>"
        )
    )
    return HTMLResponse(
        content,
        headers={"Cache-Control": "no-store", "X-Content-Type-Options": "nosniff"},
    )


def _byte_range(value: str, size: int) -> tuple[int, int] | None:
    match = re.fullmatch(r"bytes=(\d*)-(\d*)", (value or "").strip())
    if not match or size <= 0:
        return None
    start_text, end_text = match.groups()
    if not start_text:
        length = int(end_text or 0)
        if length <= 0:
            return None
        return max(0, size - length), size - 1
    start = int(start_text)
    end = min(int(end_text), size - 1) if end_text else size - 1
    if start >= size or end < start:
        return None
    return start, end


def _file_chunks(path: Path, start: int, end: int):
    remaining = end - start + 1
    with path.open("rb") as handle:
        handle.seek(start)
        while remaining:
            chunk = handle.read(min(1024 * 1024, remaining))
            if not chunk:
                break
            remaining -= len(chunk)
            yield chunk


def _media_response(request: Request, path: Path, preview):
    if preview.kind not in {"image", "video"}:
        raise HTTPException(status_code=415, detail="This is not a media reference.")
    headers = {
        "Accept-Ranges": "bytes",
        "Cache-Control": "private, no-store",
        "X-Content-Type-Options": "nosniff",
    }
    requested_range = request.headers.get("range", "")
    parsed_range = _byte_range(requested_range, preview.size)
    if requested_range and not parsed_range:
        return HTMLResponse(
            "",
            status_code=416,
            headers={**headers, "Content-Range": f"bytes */{preview.size}"},
        )
    if parsed_range:
        start, end = parsed_range
        headers.update(
            {
                "Content-Range": f"bytes {start}-{end}/{preview.size}",
                "Content-Length": str(end - start + 1),
            }
        )
        return StreamingResponse(
            _file_chunks(path, start, end),
            status_code=206,
            media_type=preview.media_type,
            headers=headers,
        )
    headers["Content-Length"] = str(preview.size)
    return FileResponse(
        path,
        filename=path.name,
        media_type=preview.media_type,
        content_disposition_type="inline",
        headers=headers,
    )


def _index_url(
    *,
    query: str,
    date_field: str,
    date_from: str,
    date_to: str,
    source: str,
    sort: str,
    page: int = 1,
    page_size: int = 20,
    show_secrets: bool = False,
    activity_year: int = 0,
) -> str:
    params = {}
    if query:
        params["q"] = query
    if date_field != "created":
        params["date_field"] = date_field
    if date_from:
        params["date_from"] = date_from
    if date_to:
        params["date_to"] = date_to
    if source:
        params["source"] = source
    if sort != "desc":
        params["sort"] = sort
    if page != 1:
        params["page"] = page
    if page_size != 20 or page != 1:
        params["page_size"] = page_size
    if show_secrets:
        params["show_secrets"] = "true"
    if activity_year and activity_year != datetime.now().year:
        params["activity_year"] = activity_year
    return "/hfl-corpus" + (f"?{urlencode(params)}" if params else "")


def _activity_level(count: int, peak: int) -> int:
    if count <= 0 or peak <= 0:
        return 0
    return min(4, max(1, math.ceil(math.log1p(count) / math.log1p(peak) * 4)))


def _activity_heatmap(
    year: int,
    counts: dict[str, int],
    *,
    selected_day: date | None = None,
    document_paths: dict[str, str] | None = None,
    start_date: date | None = None,
    end_date: date | None = None,
) -> dict[str, Any]:
    """Build a Monday-first yearly activity grid with ISO week metadata."""
    first = date(year, 1, 1)
    last = date(year, 12, 31)
    cursor = first - timedelta(days=first.weekday())
    final = last + timedelta(days=6 - last.weekday())
    today = date.today()
    peak = max(counts.values(), default=0)
    paths = document_paths or {}
    weeks = []
    index = 0
    last_labeled_month: int | None = None
    while cursor <= final:
        days = []
        month_label = ""
        for offset in range(7):
            day = cursor + timedelta(days=offset)
            in_year = day.year == year and (start_date is None or day >= start_date) and (
                end_date is None or day <= end_date
            )
            count = counts.get(day.isoformat(), 0) if in_year else 0
            if in_year and day.month != last_labeled_month:
                month_label = day.strftime("%b")
                last_labeled_month = day.month
            days.append(
                {
                    "date": day.isoformat(),
                    "day": day.day,
                    "count": count,
                    "level": _activity_level(count, peak),
                    "in_year": in_year,
                    "is_today": day == today,
                    "is_future": day > today,
                    "selected": day == selected_day,
                    "document_path": paths.get(day.isoformat(), ""),
                    "label": (
                        f"{day.strftime('%A, %d %B %Y')} · "
                        f"Week {day.isocalendar().week} · "
                        f"{count} {'entry' if count == 1 else 'entries'}"
                    ),
                }
            )
        iso_week = cursor.isocalendar().week
        weeks.append(
            {
                "days": days,
                "month": month_label,
                "week": iso_week,
                "show_week": index % 4 == 0 or iso_week == 1,
            }
        )
        cursor += timedelta(days=7)
        index += 1
    return {
        "year": year,
        "weeks": weeks,
        "peak": peak,
        "total": sum(counts.values()),
    }


@router.get("", response_class=HTMLResponse)
async def hfl_corpus_page(
    request: Request,
    q: str = "",
    date_field: str = "created",
    date_from: str = "",
    date_to: str = "",
    created_from: str = "",
    created_to: str = "",
    updated_from: str = "",
    updated_to: str = "",
    sort: str = "desc",
    page: int = 1,
    page_size: int = 20,
    created: bool = False,
    source: str = "",
    show_secrets: bool = False,
    activity_year: int = 0,
):
    user, redirect = require_user(request)
    if redirect:
        return redirect
    if date_field not in {"created", "updated", "entry"}:
        date_field = "created"
    if sort not in {"asc", "desc"}:
        sort = "desc"
    # Preserve old bookmarked URLs while presenting only the simplified UI.
    if not date_from and not date_to:
        if updated_from or updated_to:
            date_field, date_from, date_to = "updated", updated_from, updated_to
        elif created_from or created_to:
            date_field, date_from, date_to = "created", created_from, created_to
    selected_activity_day = None
    if date_field == "entry" and date_from and date_from == date_to:
        try:
            selected_activity_day = date.fromisoformat(date_from)
        except ValueError:
            pass
    requested_activity_year = activity_year or (
        selected_activity_day.year
        if selected_activity_day is not None
        else datetime.now().year
    )
    profile = get_profile_store().get()
    try:
        memory_birthdate = date.fromisoformat(profile.birthdate) if profile.birthdate else None
    except ValueError:
        memory_birthdate = None
    today = date.today()
    max_pin_date = _add_calendar_years(today, 5)
    calendar_end = max_pin_date
    timeline_start = memory_birthdate or date(today.year - 19, 1, 1)
    timeline_years = tuple(range(timeline_start.year, max_pin_date.year + 1))
    selected_timeline_year = (
        requested_activity_year if requested_activity_year in timeline_years else today.year
    )
    protected_tags = normalize_secret_tags(profile.secret_tags)
    authorized = secrets_unlocked(request, profile)
    include_secrets = bool(show_secrets and authorized)
    remote_error = ""
    if _uses_remote_corpus():
        try:
            remote = await asyncio.to_thread(
                RemoteCorpusClient.from_settings().index,
                params={
                    "q": q,
                    "date_field": date_field,
                    "date_from": date_from,
                    "date_to": date_to,
                    "source": source,
                    "sort": sort,
                    "page": str(page),
                    "page_size": str(page_size),
                    "include_secrets": str(include_secrets).lower(),
                    "secret_tags": ",".join(protected_tags),
                    "activity_year": str(requested_activity_year),
                    "activity_from_year": str(timeline_start.year),
                },
            )
            documents = remote["documents"]
            tree = remote["tree"]
            results = remote["results"]
            total_results = remote["total_results"]
            document_count = remote["document_count"]
            tag_cloud = remote["tag_cloud"]
            source_options = remote.get("sources", [])
            selected_source = remote.get("selected_source", "")
            activity = remote["activity"]
            result_page = CorpusPage(
                items=tuple(results),
                page=remote["page"],
                page_size=remote["page_size"],
                total_results=total_results,
                total_pages=remote["total_pages"],
                start=(remote["page"] - 1) * remote["page_size"] + 1 if results else 0,
                end=(remote["page"] - 1) * remote["page_size"] + len(results),
            )
        except RemoteCorpusError as exc:
            documents = ()
            tree = shallow_tree(build_tree(()))
            results = ()
            total_results = 0
            document_count = 0
            tag_cloud = []
            source_options = []
            selected_source = ""
            calendar_years = activity_calendar_years()
            activity = {
                "year": calendar_years[0],
                "years": calendar_years,
                "counts": {},
                "documents": {},
            }
            result_page = paginate_documents((), page=page, page_size=page_size)
            remote_error = str(exc)
    else:
        raw_documents = corpus_index.documents()
        view = corpus_view_cache.get(
            raw_documents,
            include_secrets=include_secrets,
            secret_tags=protected_tags,
        )
        tag_cloud = view.tag_cloud
        documents = view.documents
        source_options = view.sources
        selected_source = normalize_source(source, source_options)
        calendar_years = activity_calendar_years()
        selected_activity_year = (
            requested_activity_year
            if requested_activity_year in calendar_years
            else calendar_years[0]
        )
        activity = {
            "year": selected_activity_year,
            "years": calendar_years,
            "counts": activity_counts(
                documents,
                year=selected_activity_year,
                query=q,
                source=selected_source,
            ),
            "documents": dated_document_paths(documents),
        }
        tree = shallow_tree(view.tree)
        all_results = search_documents(
            documents,
            query=q,
            date_field=date_field,
            date_from=date_from,
            date_to=date_to,
            sort_order=sort,
            source=selected_source,
        )
        result_page = paginate_documents(all_results, page=page, page_size=page_size)
        results = result_page.items
        total_results = result_page.total_results
        document_count = len(documents)
    selected_tags, text_query = parse_search_query(q)
    entry_source_options = [
        "manual-entry",
        *(option for option in source_options if option.casefold() != "manual-entry"),
    ]
    reverse_sort = "asc" if sort == "desc" else "desc"
    sort_toggle_url = _index_url(
        query=q,
        date_field=date_field,
        date_from=date_from,
        date_to=date_to,
        source=selected_source,
        sort=reverse_sort,
        page_size=result_page.page_size,
        show_secrets=include_secrets,
        activity_year=selected_timeline_year,
    )
    tag_options = []
    for tag, count in tag_cloud:
        matching_selections = tuple(
            selected for selected in selected_tags if selected in tag.casefold()
        )
        active = bool(matching_selections)
        next_tags = tuple(
            selected for selected in selected_tags if selected not in matching_selections
        ) if active else (*selected_tags, tag)
        next_query = " ".join(
            [*(f"#{selected}" for selected in next_tags), text_query]
        ).strip()
        tag_options.append({
            "tag": tag,
            "count": count,
            "active": active,
            "url": _index_url(
                query=next_query,
                date_field=date_field,
                date_from=date_from,
                date_to=date_to,
                source=selected_source,
                sort=sort,
                page_size=result_page.page_size,
                show_secrets=include_secrets,
                activity_year=selected_timeline_year,
            ),
        })
    page_url_values = {
        "query": q,
        "date_field": date_field,
        "date_from": date_from,
        "date_to": date_to,
        "source": selected_source,
        "sort": sort,
        "page_size": result_page.page_size,
        "show_secrets": include_secrets,
        "activity_year": selected_timeline_year,
    }
    previous_page_url = _index_url(
        **page_url_values, page=result_page.page - 1
    )
    next_page_url = _index_url(
        **page_url_values, page=result_page.page + 1
    )
    today_iso = today.isoformat()
    timeline_counts = {
        key: value for key, value in dict(activity["counts"]).items() if key <= today_iso
    }
    selected_year_prefix = f"{selected_timeline_year}-"
    timeline_paths = {
        key: value
        for key, value in dict(activity.get("documents") or {}).items()
        if key.startswith(selected_year_prefix) and key <= today_iso
    }
    heatmap = _activity_heatmap(
        selected_timeline_year,
        timeline_counts,
        selected_day=selected_activity_day,
        document_paths=timeline_paths,
        start_date=timeline_start,
        end_date=calendar_end,
    )
    memory_pins = get_memory_pin_store().snapshot()
    return templates.TemplateResponse(
        request,
        "modules/hfl_corpus/index.html",
        page_context(
            request,
            user,
            "hfl_corpus",
            tree=tree,
            results=results,
            total_results=total_results,
            document_count=document_count,
            query=q,
            selected_tags=selected_tags,
            selected_tag=selected_tags[0] if len(selected_tags) == 1 else "",
            text_query=text_query,
            date_field=date_field,
            date_from=date_from,
            date_to=date_to,
            source=selected_source,
            source_options=source_options,
            entry_source_options=entry_source_options,
            sort_order=sort,
            sort_toggle_url=sort_toggle_url,
            result_page=result_page,
            previous_page_url=previous_page_url,
            next_page_url=next_page_url,
            tag_cloud=tag_options,
            remote_error=remote_error,
            success_message="HFL entry created successfully." if created else "",
            secrets_configured=bool(profile.secret_pin_hash),
            secrets_authorized=authorized,
            show_secrets=include_secrets,
            activity_year=selected_timeline_year,
            activity_years=tuple(reversed(timeline_years)),
            activity_heatmap=heatmap,
            activity_timeline_years=timeline_years,
            activity_timeline={
                "start": timeline_start.isoformat(),
                "end": today.isoformat(),
                "calendar_end": calendar_end.isoformat(),
                "counts": timeline_counts,
                "documents": timeline_paths,
                "selected_day": selected_activity_day.isoformat() if selected_activity_day else "",
                "query": q,
                "source": selected_source,
                "show_secrets": include_secrets,
            },
            activity_timeline_total=sum(timeline_counts.values()),
            activity_has_birthdate=memory_birthdate is not None,
            memory_pins=memory_pins,
            memory_csrf=make_csrf_token(user),
            today_iso=date.today().isoformat(),
            selected_activity_day=(
                selected_activity_day.isoformat()
                if selected_activity_day is not None
                else ""
            ),
        ),
    )


@router.post("/entries/preview")
async def hfl_entry_preview(request: Request, payload: CreateEntryRequest):
    user, redirect = require_user(request)
    if redirect:
        return JSONResponse({"detail": "Authentication required"}, status_code=401)
    try:
        if _uses_remote_corpus():
            return await asyncio.to_thread(
                RemoteCorpusClient.from_settings().preview_entry,
                payload.model_dump(mode="json"),
            )
        enriched, enrichment = await asyncio.to_thread(enrich_manual_entry, payload)
        return preview_manual_entry(enriched, enrichment=enrichment)
    except ValueError as exc:
        return JSONResponse({"detail": str(exc)}, status_code=400)
    except RemoteCorpusError as exc:
        return JSONResponse({"detail": str(exc)}, status_code=502)


@router.post("/entries")
async def hfl_entry_create(request: Request, payload: CreateEntryRequest):
    user, redirect = require_user(request)
    if redirect:
        return JSONResponse({"detail": "Authentication required"}, status_code=401)
    try:
        if _uses_remote_corpus():
            result = await asyncio.to_thread(
                RemoteCorpusClient.from_settings().create_entry,
                payload.model_dump(),
            )
        else:
            result = persist_manual_entry(
                payload,
                corpus_dir=resolve_corpus_root(),
            )
            corpus_index.documents(force=True)
        return result
    except ValueError as exc:
        return JSONResponse({"detail": str(exc)}, status_code=400)
    except RemoteCorpusError as exc:
        return JSONResponse({"detail": str(exc)}, status_code=502)
    except Exception:
        return JSONResponse(
            {"detail": "The entry could not be saved. Please try again."},
            status_code=500,
        )


@router.post("/entries/upload")
async def hfl_entry_upload(
    request: Request,
    payload: str = Form(...),
    files: list[UploadFile] = File(default=[]),
):
    user, redirect = require_user(request)
    if redirect:
        return JSONResponse({"detail": "Authentication required"}, status_code=401)
    try:
        entry_payload = CreateEntryRequest.model_validate_json(payload)
        if _uses_remote_corpus():
            try:
                client = RemoteCorpusClient.from_settings()
                result = await asyncio.to_thread(
                    client.create_entry_with_uploads,
                    entry_payload.model_dump(),
                    files,
                )
            finally:
                for upload in files:
                    await upload.close()
        else:
            result = await persist_manual_entry_with_uploads(
                entry_payload,
                files,
                corpus_dir=resolve_corpus_root(),
            )
            corpus_index.documents(force=True)
        return result
    except (ValueError, ValidationError, json.JSONDecodeError) as exc:
        return JSONResponse({"detail": str(exc)}, status_code=400)
    except RemoteCorpusError as exc:
        return JSONResponse({"detail": str(exc)}, status_code=502)
    except Exception:
        _log.exception("HFL manual entry upload failed")
        return JSONResponse(
            {"detail": "The entry and files could not be saved. Please try again."},
            status_code=500,
        )


@router.get("/tree", response_class=HTMLResponse, name="hfl_tree")
async def hfl_tree(request: Request, path: str = "", show_secrets: bool = False):
    user, redirect = require_user(request)
    if redirect:
        return redirect
    profile = get_profile_store().get()
    protected_tags = normalize_secret_tags(profile.secret_tags)
    include_secrets = bool(show_secrets and secrets_unlocked(request, profile))
    if _uses_remote_corpus():
        try:
            branch = await asyncio.to_thread(
                RemoteCorpusClient.from_settings().tree,
                path,
                include_secrets=include_secrets,
                secret_tags=protected_tags,
            )
        except RemoteCorpusError as exc:
            return HTMLResponse(str(exc), status_code=502)
    else:
        view = corpus_view_cache.get(
            corpus_index.documents(),
            include_secrets=include_secrets,
            secret_tags=protected_tags,
        )
        node = find_tree_node(view.tree, path)
        if not node:
            return HTMLResponse("Corpus directory not found", status_code=404)
        branch = shallow_tree(node)
    return templates.TemplateResponse(
        request,
        "modules/hfl_corpus/partials/tree.html",
        {"tree": branch, "show_secrets": include_secrets},
    )


@router.get(
    "/day-matches/{activity_day}",
    response_class=HTMLResponse,
    name="hfl_day_matches",
)
async def hfl_day_matches(
    request: Request,
    activity_day: date,
    q: str = "",
    source: str = "",
    offset: int = 0,
    limit: int = 20,
    show_secrets: bool = False,
):
    user, redirect = require_user(request)
    if redirect:
        return redirect
    profile = get_profile_store().get()
    protected_tags = normalize_secret_tags(profile.secret_tags)
    include_secrets = bool(show_secrets and secrets_unlocked(request, profile))
    if _uses_remote_corpus():
        try:
            match_page = await asyncio.to_thread(
                RemoteCorpusClient.from_settings().day_matches,
                activity_day,
                query=q,
                source=source,
                offset=offset,
                limit=limit,
                include_secrets=include_secrets,
                secret_tags=protected_tags,
            )
        except RemoteCorpusError as exc:
            return HTMLResponse(str(exc), status_code=502)
        matches = match_page["matches"]
        total = match_page["total"]
        normalized_offset = match_page["offset"]
        normalized_limit = match_page["limit"]
    else:
        view = corpus_view_cache.get(
            corpus_index.documents(),
            include_secrets=include_secrets,
            secret_tags=protected_tags,
        )
        selected_source = normalize_source(source, view.sources)
        all_matches = activity_day_entries(
            view.documents,
            activity_day=activity_day,
            query=q,
            source=selected_source,
        )
        normalized_offset = max(0, offset)
        normalized_limit = min(max(1, limit), 20)
        matches = all_matches[
            normalized_offset: normalized_offset + normalized_limit
        ]
        total = len(all_matches)
    selected_tags, _ = parse_search_query(q)
    return templates.TemplateResponse(
        request,
        "modules/hfl_corpus/partials/day_matching_entries.html",
        {
            "activity_day": activity_day,
            "matches": matches,
            "total": total,
            "offset": normalized_offset,
            "limit": normalized_limit,
            "query": q,
            "source": source,
            "selected_tag": selected_tags[0] if len(selected_tags) == 1 else "",
            "show_secrets": include_secrets,
        },
    )


@router.get(
    "/matches/{relative_path:path}",
    response_class=HTMLResponse,
    name="hfl_matches",
)
async def hfl_matches(
    request: Request,
    relative_path: str,
    q: str = "",
    source: str = "",
    offset: int = 0,
    limit: int = 20,
    show_secrets: bool = False,
):
    user, redirect = require_user(request)
    if redirect:
        return redirect
    profile = get_profile_store().get()
    protected_tags = normalize_secret_tags(profile.secret_tags)
    include_secrets = bool(show_secrets and secrets_unlocked(request, profile))
    if _uses_remote_corpus():
        try:
            match_page = await asyncio.to_thread(
                RemoteCorpusClient.from_settings().matches,
                relative_path,
                query=q,
                source=source,
                offset=offset,
                limit=limit,
                include_secrets=include_secrets,
                secret_tags=protected_tags,
            )
        except RemoteCorpusError as exc:
            return HTMLResponse(str(exc), status_code=502)
        entries = match_page["entries"]
        total = match_page["total"]
        normalized_offset = match_page["offset"]
        normalized_limit = match_page["limit"]
        document_name = relative_path.rsplit("/", 1)[-1]
    else:
        document = corpus_index.get(relative_path)
        if not document:
            return HTMLResponse("Corpus document not found", status_code=404)
        selected_tags, text_query = parse_search_query(q)
        view = corpus_view_cache.get(
            corpus_index.documents(),
            include_secrets=include_secrets,
            secret_tags=protected_tags,
        )
        selected_source = normalize_source(source, view.sources)
        visible_documents = (document,) if include_secrets else filter_documents(
            (document,), protected_tags
        )
        if not visible_documents:
            matching_entries = ()
        elif selected_tags or text_query or selected_source:
            matching_entries = visible_documents[0].matching_entries(
                selected_tags, text_query, selected_source
            )
        else:
            matching_entries = visible_documents[0].entries
        normalized_offset = max(0, offset)
        normalized_limit = min(max(1, limit), 20)
        entries = matching_entries[
            normalized_offset: normalized_offset + normalized_limit
        ]
        total = len(matching_entries)
        document_name = document.name
    selected_tags, _ = parse_search_query(q)
    return templates.TemplateResponse(
        request,
        "modules/hfl_corpus/partials/matching_entries.html",
        {
            "relative_path": relative_path,
            "document_name": document_name,
            "entries": entries,
            "total": total,
            "offset": normalized_offset,
            "limit": normalized_limit,
            "query": q,
            "source": source,
            "selected_tag": selected_tags[0] if len(selected_tags) == 1 else "",
            "show_secrets": include_secrets,
        },
    )


@router.get("/document/{relative_path:path}", response_class=HTMLResponse, name="hfl_document")
async def hfl_document(
    request: Request,
    relative_path: str,
    tag: str = "",
    source: str = "",
    show_secrets: bool = False,
    reveal: str = "",
):
    user, redirect = require_user(request)
    if redirect:
        return redirect
    profile = get_profile_store().get()
    protected_tags = normalize_secret_tags(profile.secret_tags)
    authorized = secrets_unlocked(request, profile)
    include_secrets = bool(authorized and (show_secrets or reveal))
    if _uses_remote_corpus():
        try:
            document, references = await asyncio.to_thread(
                RemoteCorpusClient.from_settings().document,
                relative_path,
                include_secrets=include_secrets,
                secret_tags=protected_tags,
            )
        except RemoteCorpusError as exc:
            return HTMLResponse(str(exc), status_code=502)
    else:
        document = corpus_index.get(relative_path)
        if not document:
            return HTMLResponse("Corpus document not found", status_code=404)
        root = resolve_corpus_root()
        source_document = document.path or (root / document.relative_path)
        references = [
            resolve_reference(reference, source_document=source_document, corpus_root=root)
            for reference in document.references
        ]
    references = [
        reference
        for reference in references
        if reference.kind in {"download", "external"} and reference.href
    ]
    if not _uses_remote_corpus():
        references = [_with_reference_preview(reference) for reference in references]
    has_secrets = document_has_secrets(document, protected_tags)
    rendered_parts: list[str] = []
    for entry in document.entries if has_secrets else ():
        secret = is_secret_entry(entry, protected_tags)
        visible = not secret or (authorized and bool(show_secrets or reveal))
        if visible:
            entry_rendered = render_markdown(
                format_hfl_markdown(f"## {entry.text}", references)
            )
            rendered_parts.append(
                str(_anchor_rendered_entries(entry_rendered, replace(document, entries=(entry,))))
            )
        else:
            anchor = html.escape(entry.anchor, quote=True)
            header = html.escape(_display_entry_header(entry.header))
            rendered_parts.append(
                f'<h2 id="{anchor}" class="scroll-mt-40">{header}</h2>'
                f'<section class="secret-entry-placeholder" data-secret-entry="{anchor}" '
                f'aria-label="Protected content for {header}">'
                '<div><strong><span aria-hidden="true">&#128274;</span> Hidden entry</strong>'
                '<p>PIN protected</p></div>'
                f'<button type="button" data-secret-reveal="{anchor}" '
                f'aria-label="Show protected content for {header}">Show</button></section>'
            )
    rendered = (
        Markup("\n".join(rendered_parts))
        if has_secrets
        else _anchor_rendered_entries(
            render_markdown(format_hfl_markdown(document.text, references)), document
        )
    )
    filtered = filter_documents((document,), protected_tags)
    display_document = document if authorized and (show_secrets or reveal) else (
        filtered[0] if filtered else replace(document, entries=(), tags=(), tag_counts=())
    )
    return templates.TemplateResponse(
        request,
        "modules/hfl_corpus/document.html",
        page_context(
            request,
            user,
            "hfl_corpus",
            document=document,
            document_text_encoded=(
                base64.b64encode(document.text.encode("utf-8")).decode("ascii")
                if not has_secrets or authorized else ""
            ),
            rendered=rendered,
            references=references,
            document_tag_counts=_document_tag_counts(display_document),
            document_source_options=_document_source_options(display_document),
            selected_source=source.casefold(),
            selected_tag="" if source else tag.casefold(),
            document_has_secrets=has_secrets,
            secrets_configured=bool(profile.secret_pin_hash),
            secrets_authorized=authorized,
            show_secrets=bool(show_secrets and authorized),
        ),
    )


@router.post("/document/{relative_path:path}")
async def hfl_document_update(
    request: Request,
    relative_path: str,
    payload: UpdateDocumentRequest,
):
    user, redirect = require_user(request)
    if redirect:
        return JSONResponse({"detail": "Authentication required"}, status_code=401)
    profile = get_profile_store().get()
    protected_tags = normalize_secret_tags(profile.secret_tags)
    try:
        if _uses_remote_corpus():
            existing_document = (await asyncio.to_thread(
                RemoteCorpusClient.from_settings().document,
                relative_path, include_secrets=True, secret_tags=protected_tags
            ))[0]
        else:
            existing_document = corpus_index.get(relative_path)
        if (
            existing_document
            and document_has_secrets(existing_document, protected_tags)
            and not secrets_unlocked(request, profile)
        ):
            return JSONResponse(
                {"detail": "Unlock secrets before editing this document."},
                status_code=403,
            )
        if _uses_remote_corpus():
            return await asyncio.to_thread(
                RemoteCorpusClient.from_settings().update_document,
                relative_path,
                payload.text,
                payload.expected_updated_at,
            )
        document = corpus_index.get(relative_path)
        if not document:
            return JSONResponse(
                {"detail": "Corpus document not found"},
                status_code=404,
            )
        path = update_document_text(
            document,
            payload.text,
            corpus_dir=resolve_corpus_root(),
            expected_updated_at=payload.expected_updated_at,
        )
        corpus_index.documents(force=True)
        return {
            "updated": True,
            "relative_path": document.relative_path,
            "size": path.stat().st_size,
        }
    except DocumentConflictError as exc:
        return JSONResponse({"detail": str(exc)}, status_code=409)
    except ValueError as exc:
        return JSONResponse({"detail": str(exc)}, status_code=400)
    except RemoteCorpusError as exc:
        return JSONResponse({"detail": str(exc)}, status_code=502)
    except OSError:
        _log.exception("HFL document update failed")
        return JSONResponse(
            {"detail": "The corpus document could not be saved."},
            status_code=500,
        )


@router.get("/references/{token}/download", name="hfl_reference_download")
async def hfl_reference_download(request: Request, token: str):
    user, redirect = require_user(request)
    if redirect:
        return redirect
    root = resolve_corpus_root()
    path = load_download_token(token, allowed_reference_roots(root))
    if not path:
        return HTMLResponse("Reference unavailable", status_code=404)
    return FileResponse(path, filename=path.name, media_type="application/octet-stream")


@router.get("/references/{token}/preview", name="hfl_reference_preview")
async def hfl_reference_preview(request: Request, token: str):
    user, redirect = require_user(request)
    if redirect:
        return redirect
    path, preview = _preview_path(token)
    return _preview_fragment(path, preview)


@router.get("/references/{token}/media", name="hfl_reference_media")
async def hfl_reference_media(request: Request, token: str):
    user, redirect = require_user(request)
    if redirect:
        return redirect
    path, preview = _preview_path(token)
    return _media_response(request, path, preview)


@router.get("/references/{token}/thumbnail", name="hfl_reference_thumbnail")
async def hfl_reference_thumbnail(request: Request, token: str):
    user, redirect = require_user(request)
    if redirect:
        return redirect
    path, preview = _preview_path(token)
    if preview.kind not in {"image", "video"}:
        raise HTTPException(status_code=415, detail="No thumbnail is available.")
    thumbnail = thumbnail_path(path, preview)
    if not thumbnail:
        raise HTTPException(status_code=404, detail="Thumbnail unavailable.")
    return FileResponse(
        thumbnail,
        media_type="image/jpeg",
        headers={
            "Cache-Control": "private, max-age=3600",
            "X-Content-Type-Options": "nosniff",
        },
    )


@router.get("/remote-references/{token}/download", name="hfl_remote_reference_download")
async def hfl_remote_reference_download(request: Request, token: str):
    user, redirect = require_user(request)
    if redirect:
        return redirect
    if not _uses_remote_corpus():
        return HTMLResponse("Remote corpus is not configured", status_code=404)
    try:
        content, filename, media_type = await asyncio.to_thread(
            RemoteCorpusClient.from_settings().download,
            token,
        )
    except RemoteCorpusError as exc:
        return HTMLResponse(str(exc), status_code=502)
    safe_filename = filename.replace('"', "")
    return Response(
        content,
        media_type=media_type,
        headers={"Content-Disposition": f"attachment; filename*=UTF-8''{quote(safe_filename)}"},
    )


async def _remote_reference_response(
    request: Request,
    token: str,
    endpoint: str,
):
    user, redirect = require_user(request)
    if redirect:
        return redirect
    if not _uses_remote_corpus():
        return HTMLResponse("Remote corpus is not configured", status_code=404)
    try:
        content, status_code, headers = await asyncio.to_thread(
            RemoteCorpusClient.from_settings().reference_content,
            token,
            endpoint,
            range_header=request.headers.get("range", ""),
        )
    except RemoteCorpusError as exc:
        return HTMLResponse(str(exc), status_code=502)
    return Response(content, status_code=status_code, headers=headers)


@router.get("/remote-references/{token}/preview")
async def hfl_remote_reference_preview(request: Request, token: str):
    return await _remote_reference_response(request, token, "preview")


@router.get("/remote-references/{token}/media")
async def hfl_remote_reference_media(request: Request, token: str):
    return await _remote_reference_response(request, token, "media")


@router.get("/remote-references/{token}/thumbnail")
async def hfl_remote_reference_thumbnail(request: Request, token: str):
    return await _remote_reference_response(request, token, "thumbnail")


from modules.hfl_corpus.timeline import router as timeline_router
router.include_router(timeline_router)
