"""Owner and guest routes for temporary Activity Corpus sharing."""

from __future__ import annotations

import asyncio
import html
import hmac
from ipaddress import ip_address
import json
import math
import re
import secrets
from collections import Counter
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import (
    FileResponse,
    HTMLResponse,
    JSONResponse,
    RedirectResponse,
    StreamingResponse,
)

from config import (
    get_settings,
    hfl_share_capacity_retry,
    hfl_share_concurrent_session_cap,
    hfl_share_question_limit,
    hfl_share_session_ttl,
)
from modules.hfl_corpus.corpus import (
    common_sources,
    common_tags,
    corpus_index,
    format_hfl_markdown,
    resolve_corpus_root,
)
from modules.hfl_corpus.remote import RemoteCorpusClient, RemoteCorpusError
from modules.hfl_corpus.secrets import normalize_secret_tags, secrets_unlocked
from modules.manifesto.service import load_manifesto
from modules.profile.store import get_profile_store
from modules.hfl_shares.agent import AgentUnavailable, answer_question
from modules.hfl_shares.audit import record_share_audit
from modules.hfl_shares.models import (
    ALL_SOURCES,
    ScopeSnapshot,
    ShareConfiguration,
    ShareGrant,
    parse_csv,
)
from modules.hfl_shares.scope import (
    build_snapshot,
    suggested_prompts,
)
from modules.hfl_shares.security import (
    REQUEST_COOKIE,
    clear_guest_cookie,
    current_grant,
    current_session,
    hash_pin,
    issue_session,
    make_csrf_token,
    make_request_cookie,
    new_pin,
    new_public_token,
    opaque_hash,
    parse_request_cookie,
    qr_data_uri,
    set_guest_cookie,
    set_request_cookie,
    valid_public_token,
    verify_csrf_token,
    verify_pin,
)
from modules.hfl_shares.store import get_share_store
from modules.hfl_shares.viewer import (
    classify_preview,
    read_preview_text,
    thumbnail_path,
)
from services.markdown import render_markdown
from services.safe_paths import allowed_reference_roots, is_within_roots
from web import page_context, require_user, templates


owner_router = APIRouter(prefix="/sharing")
guest_router = APIRouter(prefix="/share")
_OWNER_RECIPE_PAGE_SIZE = 5
_OWNER_SHARE_PAGE_SIZE = 5
_OWNER_SHARE_FORM_MAX_FIELDS = 10_000
_MAX_GUEST_SEARCH_CHARS = 500


def _validated_question(value: object) -> str:
    raw = str(value or "")
    limit = hfl_share_question_limit()
    if len(raw) > limit:
        raise ValueError(
            f"The question is too long. Questions must be {limit} "
            "characters or fewer."
        )
    question = raw.strip()
    if not question:
        raise ValueError("A question is required.")
    return question


def _profile():
    return get_profile_store().get()


def _suggested_prompts(snapshot: ScopeSnapshot) -> tuple[str, ...]:
    return suggested_prompts(snapshot, _profile().display_name)


def _secret_snapshot_options(request: Request, configuration: ShareConfiguration) -> dict:
    profile = _profile()
    if configuration.include_secrets and not secrets_unlocked(request, profile):
        raise ValueError("Unlock Activity Corpus secrets before including them.")
    return {
        "allow_secrets": configuration.include_secrets,
        "secret_tags": normalize_secret_tags(profile.secret_tags),
    }


def _sharing_documents(
    sources: tuple[str, ...] = (),
    *,
    force: bool = False,
    include_secrets: bool = False,
):
    if get_settings().hfl_corpus_api_url.strip():
        try:
            client = RemoteCorpusClient.from_settings()
            requested_sources = sources
            if not requested_sources or ALL_SOURCES in requested_sources:
                catalog = client.index(params={"page": "1", "page_size": "20"})
                requested_sources = tuple(catalog["sources"])
            if include_secrets:
                return client.sharing_documents(
                    requested_sources,
                    include_secrets=True,
                    secret_tags=normalize_secret_tags(_profile().secret_tags),
                )
            return client.sharing_documents(requested_sources)
        except RemoteCorpusError as exc:
            raise ValueError(str(exc)) from exc
    return corpus_index.documents(force=force)


def _stable_live_citations(
    snapshot: ScopeSnapshot,
    previous: ScopeSnapshot,
) -> ScopeSnapshot:
    existing = {entry.id: entry.citation for entry in previous.entries}
    used_numbers = {
        int(citation[1:])
        for citation in existing.values()
        if citation.startswith("S") and citation[1:].isdigit()
    }
    next_number = max(used_numbers, default=0) + 1
    entries = []
    for entry in snapshot.entries:
        citation = existing.get(entry.id)
        if not citation:
            citation = f"S{next_number}"
            next_number += 1
        entries.append(replace(entry, citation=citation))
    return replace(snapshot, entries=tuple(entries))


def _refresh_live_grant(grant: ShareGrant) -> ShareGrant:
    configuration = grant.live_configuration
    if not grant.live_updates or not configuration:
        return grant
    try:
        refreshed_at = datetime.fromisoformat(grant.snapshot.created_at)
        if refreshed_at.tzinfo is None:
            refreshed_at = refreshed_at.replace(tzinfo=timezone.utc)
        refresh_age = datetime.now(timezone.utc) - refreshed_at
        if refresh_age.total_seconds() < max(
            0, get_settings().hfl_share_live_refresh_seconds
        ):
            return grant
    except (TypeError, ValueError):
        pass
    try:
        snapshot = build_snapshot(
            configuration,
            _sharing_documents(
                configuration.sources,
                force=True,
                include_secrets=configuration.include_secrets,
            ),
            enabled_reference_ids=grant.snapshot.enabled_reference_ids,
            allow_secrets=configuration.include_secrets,
            secret_tags=normalize_secret_tags(_profile().secret_tags),
        )
        if not snapshot.entries:
            raise ValueError("A live share cannot refresh to an empty scope.")
        snapshot = _stable_live_citations(snapshot, grant.snapshot)
    except (TypeError, ValueError):
        return grant
    if not get_share_store().update_share_snapshot(grant.id, snapshot):
        return grant
    return replace(grant, snapshot=snapshot)


def _sharing_catalog():
    if get_settings().hfl_corpus_api_url.strip():
        try:
            remote = RemoteCorpusClient.from_settings().index(
                params={"page": "1", "page_size": "20"}
            )
        except RemoteCorpusError as exc:
            raise ValueError(str(exc)) from exc
        return (), remote["sources"], remote["tag_cloud"]
    documents = corpus_index.documents()
    return documents, common_sources(documents), common_tags(documents, limit=100)


def _normalized_sources(form: Any) -> tuple[str, ...]:
    sources = tuple(
        dict.fromkeys(
            str(item).strip()
            for item in form.getlist("sources")
            if str(item).strip()
        )
    )
    if not sources or ALL_SOURCES in sources:
        return (ALL_SOURCES,)
    return sources


def _expiration_seconds(form: Any, existing: ShareConfiguration | None) -> int:
    settings = get_settings()
    fallback = (
        existing.ttl_seconds
        if existing
        else settings.hfl_share_default_ttl_seconds
    )
    if form.get("no_expiry") == "on":
        return fallback
    raw = str(form.get("expires_at") or "").strip()
    if not raw:
        return fallback
    try:
        expires_at = datetime.fromisoformat(raw)
        offset = int(str(form.get("timezone_offset") or "0"))
        if not -840 <= offset <= 840:
            raise ValueError
        if expires_at.tzinfo is None:
            expires_at = expires_at.replace(
                tzinfo=timezone(-timedelta(minutes=offset))
            )
    except (TypeError, ValueError) as exc:
        raise ValueError("Expires at must be a valid date and time.") from exc
    seconds = math.ceil(
        (
            expires_at.astimezone(timezone.utc)
            - datetime.now(timezone.utc)
        ).total_seconds()
    )
    if seconds < 300:
        raise ValueError("Expires at must be at least five minutes from now.")
    if seconds > 31_536_000:
        raise ValueError("Expires at must be within 365 days.")
    return seconds


def _source_filtered_tags(
    documents,
    sources: tuple[str, ...],
    *,
    limit: int = 100,
) -> list[tuple[str, int]]:
    if not sources or ALL_SOURCES in sources:
        return common_tags(documents, limit=limit)
    selected = {source.casefold() for source in sources}
    counts: Counter[str] = Counter()
    for document in documents:
        tags = {
            tag
            for entry in document.entries
            if entry.source.casefold() in selected
            for tag in entry.tags
        }
        counts.update(tags)
    return sorted(counts.items(), key=lambda item: (-item[1], item[0]))[:limit]


def _sharing_tags(
    sources: tuple[str, ...],
    *,
    catalog_tags=(),
):
    if not sources or ALL_SOURCES in sources:
        if catalog_tags:
            return catalog_tags
        _, _, tags = _sharing_catalog()
        return tags
    return _source_filtered_tags(_sharing_documents(sources), sources)


def _configuration_from_form(
    form: Any,
    *,
    existing: ShareConfiguration | None = None,
    preview: bool = False,
) -> ShareConfiguration:
    settings = get_settings()
    recipient = str(form.get("recipient") or "").strip()
    if not recipient and not preview:
        raise ValueError("Recipient is required.")
    device_limit = int(
        str(form.get("device_limit") or settings.hfl_share_default_device_limit)
    )
    session_cap = hfl_share_concurrent_session_cap(settings)
    if not 1 <= device_limit <= session_cap:
        raise ValueError(
            f"Concurrent sessions must be between one and {session_cap}."
        )
    no_expiry = form.get("no_expiry") == "on"
    return ShareConfiguration(
        id=str(form.get("configuration_id") or ""),
        name=str(form.get("name") or "").strip() or ("Preview" if preview else ""),
        recipient=recipient or "there",
        description=str(form.get("description") or "").strip(),
        sources=_normalized_sources(form),
        tags=parse_csv(
            ",".join(str(item) for item in form.getlist("tags"))
        ),
        date_from=str(form.get("date_from") or "").strip(),
        date_to=str(form.get("date_to") or "").strip(),
        topic=str(form.get("topic") or "").strip(),
        selected_entry_ids=(),
        context_prompt=str(form.get("context_prompt") or "").strip(),
        auth_mode=str(form.get("auth_mode") or "pin"),
        allowed_email=str(form.get("allowed_email") or "").strip(),
        references_enabled=form.get("references_enabled") == "on",
        include_secrets=form.get("include_secrets") == "on",
        disabled_reference_ids=_disabled_references(form),
        live_updates=str(form.get("freeze_snapshot") or "on") != "on",
        ttl_seconds=_expiration_seconds(form, existing),
        no_expiry=no_expiry,
        device_limit=device_limit,
        single_use=form.get("single_use") == "on",
        created_at=existing.created_at if existing else "",
        updated_at=existing.updated_at if existing else "",
    )


def _disabled_references(form: Any) -> tuple[str, ...]:
    return tuple(str(item) for item in form.getlist("disabled_reference_ids"))


def _require_csrf(form: Any, user: str) -> None:
    if not verify_csrf_token(str(form.get("csrf") or ""), user):
        raise HTTPException(status_code=403, detail="Invalid form token.")


async def _guest_form(request: Request):
    """Parse a small public form without accepting an unbounded request body."""
    limit = max(1_024, get_settings().hfl_share_max_guest_request_bytes)
    content_length = request.headers.get("content-length", "").strip()
    try:
        if content_length and int(content_length) > limit:
            raise HTTPException(status_code=413, detail="Request body is too large.")
    except ValueError as exc:
        raise HTTPException(
            status_code=400,
            detail="Invalid Content-Length header.",
        ) from exc
    body = await request.body()
    if len(body) > limit:
        raise HTTPException(status_code=413, detail="Request body is too large.")
    return await request.form(max_files=0, max_fields=10)


def _owner_page(items: list[Any], raw_page: str, page_size: int):
    try:
        requested = max(1, int(raw_page or "1"))
    except ValueError:
        requested = 1
    total_pages = max(1, math.ceil(len(items) / page_size))
    page = min(requested, total_pages)
    start = (page - 1) * page_size
    return items[start : start + page_size], page, total_pages


def _owner_page_number(total: int, raw_page: str, page_size: int) -> tuple[int, int]:
    try:
        requested = max(1, int(raw_page or "1"))
    except ValueError:
        requested = 1
    total_pages = max(1, math.ceil(total / page_size))
    return min(requested, total_pages), total_pages


def _generated_shares_context_sync(request: Request, user: str) -> dict[str, Any]:
    """Build only the inexpensive generated-share list fragment context."""
    store = get_share_store()
    share_count = store.count_shares()
    share_page, share_total_pages = _owner_page_number(
        share_count,
        request.query_params.get("share_page", "1"),
        _OWNER_SHARE_PAGE_SIZE,
    )
    share_page_items = store.list_share_summaries(
        limit=_OWNER_SHARE_PAGE_SIZE,
        offset=(share_page - 1) * _OWNER_SHARE_PAGE_SIZE,
    )
    try:
        recipe_page = max(
            1,
            int(request.query_params.get("recipe_page", "1") or "1"),
        )
    except ValueError:
        recipe_page = 1
    return {
        "request": request,
        "shares": tuple(
            {
                "grant": share,
                "status": (
                    "revoked"
                    if share.status == "revoked"
                    else "expired" if share.expired else share.status
                ),
                "expires_at_display": _expiry_display(share),
            }
            for share in share_page_items
        ),
        "share_page": share_page,
        "share_total_pages": share_total_pages,
        "share_count": share_count,
        "recipe_page": recipe_page,
        "configuration_id": request.query_params.get("configuration_id", ""),
        "csrf": make_csrf_token(user),
    }


def _owner_context_sync(
    request: Request,
    user: str,
    *,
    configuration: ShareConfiguration | None = None,
    preview=None,
    preview_answer: str = "",
    preview_question: str = "",
    error: str = "",
    success: str = "",
) -> dict[str, Any]:
    try:
        documents, catalog_sources, catalog_tags = _sharing_catalog()
        corpus_error = ""
    except ValueError as exc:
        documents = ()
        catalog_sources = ()
        catalog_tags = ()
        corpus_error = str(exc)
    store = get_share_store()
    sources = set(catalog_sources)
    if configuration:
        sources.update(
            source
            for source in configuration.sources
            if source != ALL_SOURCES
        )
    selected_sources = (
        configuration.sources
        if configuration
        else (ALL_SOURCES,)
    )
    try:
        filtered_tags = _sharing_tags(
            selected_sources,
            catalog_tags=catalog_tags,
        )
    except ValueError as exc:
        filtered_tags = catalog_tags
        corpus_error = corpus_error or str(exc)
    tag_counts = dict(filtered_tags)
    for tag in configuration.tags if configuration else ():
        tag_counts.setdefault(tag, 0)
    available_tags = sorted(
        tag_counts.items(),
        key=lambda item: (-item[1], item[0]),
    )
    ttl_seconds = (
        configuration.ttl_seconds
        if configuration
        else 86_400
    )
    default_expires_at = (
        datetime.now().astimezone() + timedelta(seconds=ttl_seconds)
    ).strftime("%Y-%m-%dT%H:%M")
    all_configurations = store.list_configurations()
    configuration_page_items, recipe_page, recipe_total_pages = _owner_page(
        all_configurations,
        request.query_params.get("recipe_page", "1"),
        _OWNER_RECIPE_PAGE_SIZE,
    )
    share_count = store.count_shares()
    share_page, share_total_pages = _owner_page_number(
        share_count,
        request.query_params.get("share_page", "1"),
        _OWNER_SHARE_PAGE_SIZE,
    )
    share_page_items = store.list_share_summaries(
        limit=_OWNER_SHARE_PAGE_SIZE,
        offset=(share_page - 1) * _OWNER_SHARE_PAGE_SIZE,
    )
    return page_context(
        request,
        user,
        "sharing",
        configurations=tuple(
            {
                "configuration": item,
                "expiration_summary": (
                    "No expiry"
                    if item.no_expiry
                    else _duration_summary(item.ttl_seconds)
                ),
            }
            for item in configuration_page_items
        ),
        shares=tuple(
            {
                "grant": share,
                "status": (
                    "revoked"
                    if share.status == "revoked"
                    else "expired" if share.expired else share.status
                ),
                "expires_at_display": _expiry_display(share),
            }
            for share in share_page_items
        ),
        recipe_page=recipe_page,
        recipe_total_pages=recipe_total_pages,
        recipe_count=len(all_configurations),
        share_page=share_page,
        share_total_pages=share_total_pages,
        share_count=share_count,
        pending_requests=store.list_pending_requests(),
        available_sources=tuple(sorted(sources, key=str.casefold)),
        available_tags=available_tags,
        all_sources_value=ALL_SOURCES,
        default_expires_at=default_expires_at,
        configuration=configuration,
        preview=preview,
        preview_answer=preview_answer,
        preview_question=preview_question,
        suggested_prompts=_suggested_prompts(preview) if preview else (),
        error=error or corpus_error,
        success=success,
        csrf=make_csrf_token(user),
        defaults=get_settings(),
        max_concurrent_sessions=hfl_share_concurrent_session_cap(),
        session_duration=_session_duration_summary(),
        secrets_configured=bool(_profile().secret_pin_hash),
        secrets_authorized=secrets_unlocked(request, _profile()),
    )


async def _owner_context(*args, **kwargs) -> dict[str, Any]:
    """Build the owner page without blocking the frontend event loop."""
    return await asyncio.to_thread(_owner_context_sync, *args, **kwargs)


@owner_router.get("/filter-options")
async def sharing_filter_options(request: Request):
    user, redirect = require_user(request)
    if redirect:
        return JSONResponse(
            {"detail": "Authentication required."},
            status_code=401,
        )
    sources = tuple(request.query_params.getlist("source")) or (ALL_SOURCES,)
    try:
        tags = _sharing_tags(sources)
    except ValueError as exc:
        return JSONResponse({"detail": str(exc)}, status_code=503)
    return {"tags": [[tag, count] for tag, count in tags]}


@owner_router.get("", response_class=HTMLResponse)
async def sharing_page(
    request: Request,
    configuration_id: str = "",
    duplicate: bool = False,
    notice: str = "",
):
    user, redirect = require_user(request)
    if redirect:
        return redirect
    configuration = None
    success = ""
    if configuration_id:
        configuration = await asyncio.to_thread(
            lambda: get_share_store().get_configuration(configuration_id)
        )
        if configuration and duplicate:
            configuration = ShareConfiguration(
                **{
                    **configuration.to_record(),
                    "id": "",
                    "name": f"{configuration.name} copy",
                    "created_at": "",
                    "updated_at": "",
                }
            )
        elif configuration and notice in {"saved", "updated"}:
            action = "saved" if notice == "saved" else "updated"
            success = f"{configuration.name} {action}."
    return templates.TemplateResponse(
        request,
        "modules/hfl_shares/index.html",
        await _owner_context(
            request,
            user,
            configuration=configuration,
            success=success,
        ),
    )


@owner_router.get("/generated-shares", response_class=HTMLResponse)
async def generated_shares_fragment(request: Request):
    user, redirect = require_user(request)
    if redirect:
        return redirect
    context = await asyncio.to_thread(
        _generated_shares_context_sync,
        request,
        user,
    )
    return templates.TemplateResponse(
        request,
        "modules/hfl_shares/partials/generated_shares.html",
        context,
    )


@owner_router.post("/configurations", response_class=HTMLResponse)
async def save_configuration(request: Request):
    user, redirect = require_user(request)
    if redirect:
        return redirect
    form = await request.form(max_fields=_OWNER_SHARE_FORM_MAX_FIELDS)
    _require_csrf(form, user)
    store = get_share_store()
    existing = store.get_configuration(str(form.get("configuration_id") or ""))
    notice = "updated" if existing else "saved"
    try:
        configuration = _configuration_from_form(form, existing=existing)
        saved = store.save_configuration(configuration)
    except (TypeError, ValueError) as exc:
        return templates.TemplateResponse(
            request,
            "modules/hfl_shares/index.html",
            await _owner_context(request, user, error=str(exc)),
            status_code=422,
        )
    return RedirectResponse(
        f"/sharing?configuration_id={saved.id}&notice={notice}",
        status_code=303,
    )


@owner_router.post("/configurations/{configuration_id}/delete")
async def delete_configuration(request: Request, configuration_id: str):
    user, redirect = require_user(request)
    if redirect:
        return redirect
    form = await request.form()
    _require_csrf(form, user)
    get_share_store().delete_configuration(configuration_id)
    return RedirectResponse("/sharing", status_code=303)


def _build_preview_snapshot(
    request: Request,
    configuration: ShareConfiguration,
    disabled_reference_ids: tuple[str, ...],
) -> ScopeSnapshot:
    """Keep corpus loading and reference resolution off the request event loop."""
    return build_snapshot(
        configuration,
        _sharing_documents(
            configuration.sources, include_secrets=configuration.include_secrets
        ),
        disabled_reference_ids=disabled_reference_ids,
        **_secret_snapshot_options(request, configuration),
    )


async def _preview_response(
    request: Request,
    user: str,
    *,
    with_agent: bool,
    fragment: bool = False,
) -> HTMLResponse:
    form = await request.form(max_fields=_OWNER_SHARE_FORM_MAX_FIELDS)
    _require_csrf(form, user)
    store = get_share_store()
    existing = store.get_configuration(str(form.get("configuration_id") or ""))
    try:
        question = (
            _validated_question(form.get("question"))
            if with_agent
            else str(form.get("question") or "").strip()
        )
        configuration = _configuration_from_form(
            form,
            existing=existing,
            preview=fragment,
        )
        preview = await asyncio.to_thread(
            _build_preview_snapshot,
            request,
            configuration,
            _disabled_references(form),
        )
        answer = ""
        if with_agent:
            answer = await answer_question(preview, question)
    except (AgentUnavailable, TypeError, ValueError) as exc:
        if fragment:
            return templates.TemplateResponse(
                request,
                "modules/hfl_shares/_preview.html",
                {
                    "request": request,
                    "preview": locals().get("preview"),
                    "preview_question": str(form.get("question") or ""),
                    "preview_answer": "",
                    "suggested_prompts": (),
                    "preview_error": str(exc),
                },
                status_code=422,
            )
        return templates.TemplateResponse(
            request,
            "modules/hfl_shares/index.html",
            await _owner_context(
                request,
                user,
                configuration=locals().get("configuration"),
                preview=locals().get("preview"),
                preview_question=str(form.get("question") or ""),
                error=str(exc),
            ),
            status_code=422,
        )
    if fragment:
        return templates.TemplateResponse(
            request,
            "modules/hfl_shares/_preview.html",
            {
                "request": request,
                "preview": preview,
                "preview_question": question,
                "preview_answer": answer,
                "suggested_prompts": _suggested_prompts(preview),
                "preview_error": "",
            },
        )
    return templates.TemplateResponse(
        request,
        "modules/hfl_shares/index.html",
        await _owner_context(
            request,
            user,
            configuration=configuration,
            preview=preview,
            preview_answer=answer,
            preview_question=question,
        ),
    )


@owner_router.post("/preview", response_class=HTMLResponse)
async def preview_scope(request: Request, fragment: bool = False):
    user, redirect = require_user(request)
    if redirect:
        return redirect
    return await _preview_response(
        request,
        user,
        with_agent=False,
        fragment=fragment,
    )


@owner_router.post("/preview/chat", response_class=HTMLResponse)
async def preview_chat(request: Request):
    user, redirect = require_user(request)
    if redirect:
        return redirect
    return await _preview_response(request, user, with_agent=True)


def _valid_public_hostname(hostname: str) -> bool:
    try:
        ip_address(hostname)
    except ValueError:
        if len(hostname) > 253:
            return False
        return all(
            re.fullmatch(
                r"[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?",
                label,
            )
            for label in hostname.split(".")
        )
    return True


def _public_share_origin(request: Request) -> str:
    settings = get_settings()
    configured = settings.hfl_share_public_url.strip()
    if settings.behind_proxy and not configured:
        raise ValueError(
            "HFL_SHARE_PUBLIC_URL must be configured when the frontend is "
            "behind a proxy."
        )
    base = configured or str(request.base_url)
    if any(
        ord(character) <= 32 or character in {"\\", "%"}
        for character in base
    ):
        raise ValueError(
            "HFL_SHARE_PUBLIC_URL must be an origin only, without ambiguous "
            "authority characters."
        )
    parsed = urlparse(base)
    if not parsed.scheme or not parsed.netloc:
        raise ValueError("HFL_SHARE_PUBLIC_URL must be an absolute URL.")
    try:
        hostname = parsed.hostname
        port = parsed.port
    except ValueError as exc:
        raise ValueError(
            "HFL_SHARE_PUBLIC_URL must be an origin only with a valid port."
        ) from exc
    if not hostname:
        raise ValueError("HFL_SHARE_PUBLIC_URL must be an absolute URL.")
    authority = parsed.netloc.rsplit("@", 1)[-1]
    if authority.endswith(":") or port == 0 or not _valid_public_hostname(hostname):
        raise ValueError(
            "HFL_SHARE_PUBLIC_URL must be an origin only with a valid "
            "hostname and port."
        )
    if settings.behind_proxy and parsed.scheme != "https":
        raise ValueError(
            "HFL_SHARE_PUBLIC_URL must be an HTTPS URL when the frontend "
            "is behind a proxy."
        )
    if parsed.scheme not in {"http", "https"}:
        raise ValueError("HFL_SHARE_PUBLIC_URL must use HTTP or HTTPS.")
    if (
        parsed.username is not None
        or parsed.password is not None
        or parsed.path not in {"", "/"}
        or parsed.params
        or parsed.query
        or parsed.fragment
    ):
        raise ValueError(
            "HFL_SHARE_PUBLIC_URL must be an origin only, without credentials, "
            "a path, query, or fragment."
        )
    return f"{parsed.scheme}://{parsed.netloc}"


@owner_router.post("/generate", response_class=HTMLResponse)
async def generate_share(request: Request):
    user, redirect = require_user(request)
    if redirect:
        return redirect
    form = await request.form(max_fields=_OWNER_SHARE_FORM_MAX_FIELDS)
    _require_csrf(form, user)
    store = get_share_store()
    existing = store.get_configuration(str(form.get("configuration_id") or ""))
    try:
        configuration = _configuration_from_form(form, existing=existing)
        snapshot = build_snapshot(
            configuration,
            _sharing_documents(
                configuration.sources,
                force=True,
                include_secrets=configuration.include_secrets,
            ),
            disabled_reference_ids=_disabled_references(form),
            **_secret_snapshot_options(request, configuration),
        )
        if not snapshot.entries:
            raise ValueError("A share cannot be generated from an empty scope.")
        settings = get_settings()
        if snapshot.estimated_chars > settings.hfl_share_max_snapshot_chars:
            raise ValueError(
                "The scope is too large to share. Narrow its sources or filters."
            )
        public_token = new_public_token()
        pin = new_pin() if configuration.auth_mode == "pin" else ""
        base = _public_share_origin(request)
        access_path = (
            "email" if configuration.auth_mode == "email_otp" else "access"
        )
        link = f"{base}/share/{access_path}/{public_token}"
        qr = qr_data_uri(link)
        grant = store.create_share(
            configuration_id=configuration.id,
            name=configuration.name,
            token_hash=opaque_hash(public_token),
            pin_hash=hash_pin(pin) if pin else "",
            auth_mode=configuration.auth_mode,
            allowed_email=configuration.allowed_email,
            snapshot=snapshot,
            live_configuration=(
                configuration if configuration.live_updates else None
            ),
            ttl_seconds=configuration.ttl_seconds,
            no_expiry=configuration.no_expiry,
            single_use=configuration.single_use,
            device_limit=configuration.device_limit,
        )
        generated = {
            "grant": grant,
            "link": link,
            "pin": pin,
            "qr": qr,
            "expires_at_display": _expiry_display(grant),
            "share_recipient": grant.snapshot.recipient,
            "session_duration": _session_duration_summary(),
        }
        record_share_audit(event="created", share_id=grant.id)
    except (TypeError, ValueError) as exc:
        return templates.TemplateResponse(
            request,
            "modules/hfl_shares/index.html",
            await _owner_context(
                request,
                user,
                configuration=locals().get("configuration"),
                preview=locals().get("snapshot"),
                error=str(exc),
            ),
            status_code=422,
        )
    response = templates.TemplateResponse(
        request,
        "modules/hfl_shares/generated.html",
        {"request": request, **generated},
    )
    response.headers["Cache-Control"] = "no-store"
    response.headers["Referrer-Policy"] = "no-referrer"
    response.headers["Content-Security-Policy"] = (
        "default-src 'self'; img-src 'self' data:; "
        "style-src 'self' 'unsafe-inline'; form-action 'self'; "
        "frame-ancestors 'none'; base-uri 'none'"
    )
    return response


@owner_router.post("/shares/{share_id}/revoke")
async def revoke_share(request: Request, share_id: str):
    user, redirect = require_user(request)
    if redirect:
        return redirect
    form = await request.form()
    _require_csrf(form, user)
    if get_share_store().revoke_share(share_id):
        record_share_audit(event="revoked", share_id=share_id)
    return RedirectResponse("/sharing", status_code=303)


@owner_router.get("/shares/{share_id}/preview", response_class=HTMLResponse)
async def preview_generated_share(
    request: Request,
    share_id: str,
    q: str = "",
    page: int = 1,
    fragment: bool = False,
):
    user, redirect = require_user(request)
    if redirect:
        return redirect
    grant = get_share_store().get_share(share_id)
    if not grant or not grant.available:
        raise HTTPException(status_code=404, detail="Active share not found.")
    grant = _refresh_live_grant(grant)
    selected_tags = tuple(request.query_params.getlist("tag"))
    context = _guest_context(
        request,
        grant,
        f"owner-preview:{user}:{grant.id}",
        query=q,
        selected_tags=selected_tags,
        page=page,
        owner_preview=True,
    )
    context["preview_csrf"] = make_csrf_token(user)
    response = templates.TemplateResponse(
        request,
        (
            "modules/hfl_shares/_guest_entries.html"
            if fragment
            else "modules/hfl_shares/guest.html"
        ),
        context,
    )
    if fragment:
        response.headers["X-HFL-Result-Count"] = str(context["result_count"])
    response.headers["Cache-Control"] = "no-store"
    return response


@owner_router.post("/configurations/{configuration_id}/instant")
async def generate_instant_share(request: Request, configuration_id: str):
    user, redirect = require_user(request)
    if redirect:
        return JSONResponse(
            {"detail": "Authentication required."},
            status_code=401,
        )
    form = await request.form()
    _require_csrf(form, user)
    store = get_share_store()
    saved = store.get_configuration(configuration_id)
    if not saved:
        return JSONResponse(
            {"detail": "The saved recipe no longer exists."},
            status_code=404,
        )
    configuration = replace(
        saved,
        auth_mode="qr",
        allowed_email="",
        references_enabled=True,
        ttl_seconds=86_400,
        no_expiry=False,
        device_limit=1,
        single_use=True,
    )
    try:
        snapshot = build_snapshot(
            configuration,
            _sharing_documents(
                configuration.sources,
                force=True,
                include_secrets=configuration.include_secrets,
            ),
            **_secret_snapshot_options(request, configuration),
        )
        if not snapshot.entries:
            raise ValueError("A share cannot be generated from an empty scope.")
        settings = get_settings()
        if snapshot.estimated_chars > settings.hfl_share_max_snapshot_chars:
            raise ValueError(
                "The scope is too large to share. Narrow its sources or filters."
            )
        public_token = new_public_token()
        base = _public_share_origin(request)
        link = f"{base}/share/access/{public_token}"
        grant = store.create_share(
            configuration_id=configuration.id,
            name=configuration.name,
            token_hash=opaque_hash(public_token),
            pin_hash="",
            auth_mode="qr",
            allowed_email="",
            snapshot=snapshot,
            live_configuration=(
                configuration if configuration.live_updates else None
            ),
            ttl_seconds=86_400,
            no_expiry=False,
            single_use=True,
            device_limit=1,
            instant=True,
        )
        record_share_audit(event="created", share_id=grant.id)
    except (TypeError, ValueError) as exc:
        return JSONResponse({"detail": str(exc)}, status_code=422)
    response = JSONResponse(
        {
            "name": grant.name,
            "qr": qr_data_uri(link),
            "expires": "1 day",
            "devices": 1,
            "single_use": True,
            "references_enabled": True,
        }
    )
    response.headers["Cache-Control"] = "no-store"
    response.headers["Referrer-Policy"] = "no-referrer"
    return response


def _manifesto_fragment(request: Request) -> HTMLResponse:
    response = templates.TemplateResponse(
        request,
        "modules/hfl_shares/_manifesto.html",
        {"manifesto": load_manifesto()},
    )
    response.headers["Cache-Control"] = "no-store"
    return response


@owner_router.get(
    "/shares/{share_id}/preview/manifesto",
    response_class=HTMLResponse,
)
async def preview_generated_share_manifesto(
    request: Request,
    share_id: str,
):
    user, redirect = require_user(request)
    if redirect:
        return HTMLResponse(
            '<p class="notice error">Manifesto access requires owner authentication.</p>',
            status_code=401,
            headers={"Cache-Control": "no-store"},
        )
    grant = get_share_store().get_share(share_id)
    if not grant or not grant.available:
        return HTMLResponse(
            '<p class="notice error">This shared Manifesto is no longer available.</p>',
            status_code=404,
            headers={"Cache-Control": "no-store"},
        )
    return _manifesto_fragment(request)


@owner_router.post("/shares/{share_id}/preview/chat")
async def preview_generated_share_chat(request: Request, share_id: str):
    user, redirect = require_user(request)
    if redirect:
        return JSONResponse({"detail": "Authentication required."}, status_code=401)
    grant = get_share_store().get_share(share_id)
    if not grant or not grant.available:
        return JSONResponse({"detail": "Active share not found."}, status_code=404)
    form = await request.form()
    try:
        _require_csrf(form, user)
    except HTTPException:
        return JSONResponse({"detail": "Invalid form token."}, status_code=403)
    try:
        question = _validated_question(form.get("question"))
        raw_history = json.loads(str(form.get("history") or "[]"))
        if not isinstance(raw_history, list):
            raise ValueError("Preview conversation history is invalid.")
        history = tuple(
            {
                "role": (
                    "assistant"
                    if str(item.get("role") or "") == "assistant"
                    else "user"
                ),
                "content": str(item.get("content") or "")[:4_000],
            }
            for item in raw_history[-8:]
            if isinstance(item, dict) and str(item.get("content") or "").strip()
        )
        grant = _refresh_live_grant(grant)
        answer = await answer_question(
            grant.snapshot,
            question,
            history=history,
            share_id=grant.id,
        )
    except (AgentUnavailable, TypeError, ValueError, json.JSONDecodeError) as exc:
        return JSONResponse({"detail": str(exc)}, status_code=422)
    now = _format_utc(datetime.now(timezone.utc).isoformat())
    return JSONResponse(
        {
            "user": {"content": question, "created_at": now},
            "assistant": {
                "content": answer,
                "html": str(
                    _answer_html(
                        answer,
                        _citation_pages(grant),
                        f"/sharing/shares/{grant.id}/preview",
                    )
                ),
                "created_at": now,
            },
        }
    )


@owner_router.post("/requests/{request_id}/approve")
async def approve_request(request: Request, request_id: str):
    user, redirect = require_user(request)
    if redirect:
        return redirect
    form = await request.form()
    _require_csrf(form, user)
    get_share_store().approve_request(request_id)
    return RedirectResponse("/sharing", status_code=303)


def _unavailable(request: Request, status_code: int = 404) -> HTMLResponse:
    return templates.TemplateResponse(
        request,
        "modules/hfl_shares/unavailable.html",
        {"request": request},
        status_code=status_code,
    )


def _access_context(
    request: Request,
    grant: ShareGrant,
    token: str,
    *,
    error: str = "",
) -> dict[str, Any]:
    return {
        "request": request,
        "grant": grant,
        "token": token,
        "error": error,
        "expires_at_display": _expiry_display(grant),
        "share_recipient": grant.snapshot.recipient,
        "session_duration": _session_duration_summary(),
    }


def _capacity_response(
    request: Request,
    grant: ShareGrant,
    token: str,
) -> HTMLResponse:
    response = templates.TemplateResponse(
        request,
        "modules/hfl_shares/access.html",
        _access_context(
            request,
            grant,
            token,
            error=(
                f"All {grant.device_limit} sessions are currently in use. "
                "Try again after a session is closed or expires."
            ),
        ),
        status_code=429,
    )
    response.headers["Retry-After"] = str(hfl_share_capacity_retry())
    return response


@guest_router.get("/access/{token}", response_class=HTMLResponse)
@guest_router.get("/email/{token}", response_class=HTMLResponse)
async def share_access(request: Request, token: str):
    if not valid_public_token(token):
        return _unavailable(request)
    grant = get_share_store().get_share_by_token_hash(opaque_hash(token))
    if not grant or not grant.available:
        return _unavailable(request)
    return templates.TemplateResponse(
        request,
        "modules/hfl_shares/access.html",
        _access_context(request, grant, token),
    )


@guest_router.post("/access/{token}/redeem")
@guest_router.post("/email/{token}/redeem")
async def redeem_share(request: Request, token: str):
    if not valid_public_token(token):
        return _unavailable(request)
    store = get_share_store()
    grant = store.get_share_by_token_hash(opaque_hash(token))
    if not grant or not grant.available:
        return _unavailable(request)
    existing_session = current_session(request, store)
    if existing_session and existing_session[0].id == grant.id:
        record_share_audit(event="session-resumed", share_id=grant.id)
        return RedirectResponse("/share/session", status_code=303)
    form = await _guest_form(request)
    if grant.auth_mode == "pin":
        settings = get_settings()
        if store.pin_rate_limited(
            grant.id,
            settings.hfl_share_pin_max_attempts,
            settings.hfl_share_pin_attempt_window_seconds,
        ):
            response = _unavailable(request, status_code=429)
            response.headers["Retry-After"] = str(
                settings.hfl_share_pin_attempt_window_seconds
            )
            return response
        pin = str(form.get("pin") or "")
        if not re.fullmatch(r"[0-9]{8}", pin) or not verify_pin(
            pin, store.pin_hash_for_share(grant.id)
        ):
            store.record_pin_failure(grant.id)
            record_share_audit(event="failed-redemption", share_id=grant.id)
            return templates.TemplateResponse(
                request,
                "modules/hfl_shares/access.html",
                _access_context(
                    request,
                    grant,
                    token,
                    error="The access details were not accepted.",
                ),
                status_code=403,
            )
        store.clear_recent_pin_failures(grant.id)
    elif grant.auth_mode == "email_otp":
        settings = get_settings()
        email = request.headers.get(
            "Cf-Access-Authenticated-User-Email", ""
        ).strip()
        assertion = request.headers.get("Cf-Access-Jwt-Assertion", "").strip()
        if (
            not settings.behind_proxy
            or not settings.hfl_share_trust_proxy_identity
            or not assertion
            or not hmac.compare_digest(email.casefold(), grant.allowed_email.casefold())
        ):
            return _unavailable(request, status_code=403)
    elif grant.auth_mode == "manual":
        secret = secrets.token_urlsafe(32)
        created_request = store.create_access_request(
            grant.id, opaque_hash(secret)
        )
        if not created_request:
            return _unavailable(request, status_code=429)
        request_id, _ = created_request
        response = RedirectResponse("/share/pending", status_code=303)
        set_request_cookie(
            response, make_request_cookie(request_id, secret)
        )
        record_share_audit(event="approval-requested", share_id=grant.id)
        return response
    elif grant.auth_mode != "qr":
        return _unavailable(request)

    issued = issue_session(store, grant.id)
    if not issued:
        if (
            not grant.single_use
            and store.active_session_count(grant.id) >= grant.device_limit
        ):
            return _capacity_response(request, grant, token)
        return _unavailable(request, status_code=403)
    if existing_session:
        store.revoke_session(existing_session[1])
    response = RedirectResponse("/share/session", status_code=303)
    set_guest_cookie(response, issued.cookie, issued.max_age)
    record_share_audit(event="redeemed", share_id=grant.id)
    return response


@guest_router.get("/pending", response_class=HTMLResponse)
async def pending_access(request: Request):
    parsed = parse_request_cookie(request)
    if not parsed:
        return _unavailable(request)
    request_id, secret = parsed
    store = get_share_store()
    access_request = store.get_access_request(request_id, opaque_hash(secret))
    if not access_request:
        return _unavailable(request)
    if access_request["status"] == "approved":
        existing_session = current_session(request, store)
        issued = issue_session(store, access_request["share_id"])
        if not issued:
            return _unavailable(request, status_code=403)
        if existing_session:
            store.revoke_session(existing_session[1])
        store.consume_approved_request(request_id)
        response = RedirectResponse("/share/session", status_code=303)
        set_guest_cookie(response, issued.cookie, issued.max_age)
        response.delete_cookie(REQUEST_COOKIE, path="/share")
        record_share_audit(
            event="redeemed", share_id=access_request["share_id"]
        )
        return response
    if access_request["status"] != "pending":
        return _unavailable(request)
    return templates.TemplateResponse(
        request,
        "modules/hfl_shares/pending.html",
        {"request": request},
    )


def _normalized_guest_tags(tags) -> tuple[str, ...]:
    normalized: dict[str, str] = {}
    for raw_tag in tags:
        tag = str(raw_tag).strip()
        if tag:
            normalized.setdefault(tag.casefold(), tag)
    return tuple(normalized.values())


def _guest_entries(
    grant,
    query: str,
    tags: tuple[str, ...] = (),
):
    needle = (query or "").strip().casefold()
    selected_tags = {tag.casefold() for tag in _normalized_guest_tags(tags)}
    matches = tuple(
        entry
        for entry in grant.snapshot.entries
        if (
            not needle
            or needle
            in " ".join(
                (
                    entry.moment,
                    entry.what_happened,
                    entry.source,
                    " ".join(entry.tags),
                    entry.text,
                )
            ).casefold()
        )
        and selected_tags.issubset(
            {tag.casefold() for tag in entry.tags}
        )
    )
    return tuple(
        sorted(
            matches,
            key=lambda entry: _snapshot_entry_datetime(entry.header)
            or datetime.min,
            reverse=True,
        )
    )


def _snapshot_entry_datetime(header: str) -> datetime | None:
    raw = (header or "").strip()
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%d"):
        try:
            return datetime.strptime(raw, fmt)
        except ValueError:
            continue
    try:
        return datetime.fromisoformat(raw).replace(tzinfo=None)
    except ValueError:
        return None


_PUBLIC_ENTRY_DROP = re.compile(
    r"^\s*(?:#{1,6}\s+|Source\s*:|Tags\s*:)",
    re.IGNORECASE,
)
_NATURAL_EVIDENCE = re.compile(r"\[\[([^\]\n|]{1,160})\|S(\d+)\]\]")
_EVIDENCE = re.compile(r"\[S(\d+)\]")
_GUEST_PAGE_SIZE = 10


def _format_utc(value: str) -> str:
    try:
        parsed = datetime.fromisoformat(value).astimezone(timezone.utc)
    except (TypeError, ValueError):
        return value
    return (
        f"{parsed.strftime('%B')} {parsed.day:02d}, {parsed.year} "
        f"{parsed.strftime('%I:%M %p').lstrip('0')} UTC"
    )


def _expiry_display(grant) -> str:
    return "No expiry" if grant.no_expiry else _format_utc(grant.expires_at)


def _duration_summary(seconds: int) -> str:
    total_seconds = max(0, int(seconds))
    if total_seconds < 3_600:
        return "expires in less than 1 hour"
    total_hours = total_seconds // 3_600
    if total_seconds < 604_800:
        days, hours = divmod(total_hours, 24)
        parts: list[str] = []
        if days:
            parts.append(f"{days} day{'s' if days != 1 else ''}")
        if hours:
            parts.append(f"{hours} hour{'s' if hours != 1 else ''}")
        return "expires in " + " ".join(parts)
    days = max(7, total_seconds // 86_400)
    return f"expires after {days} days"


def _session_duration_summary() -> str:
    seconds = hfl_share_session_ttl()
    summary = _duration_summary(seconds)
    return summary.removeprefix("expires in ").removeprefix("expires after ")


def _entry_html(entry):
    public_text = "\n".join(
        line
        for line in entry.text.splitlines()
        if not _PUBLIC_ENTRY_DROP.match(line)
    )
    return render_markdown(format_hfl_markdown(public_text))


def _reference_views(entry, *, base_url: str) -> dict[str, dict[str, str]]:
    views: dict[str, dict[str, str]] = {}
    for reference in entry.references:
        if not reference.enabled:
            continue
        download_url = f"{base_url}/{reference.id}"
        view = {
            "kind": "",
            "download_url": download_url,
            "preview_url": "",
            "media_url": "",
            "thumbnail_url": "",
        }
        if reference.kind != "external":
            preview = classify_preview(Path(reference.target))
            if preview:
                view.update(
                    {
                        "kind": preview.kind,
                        "preview_url": f"{download_url}/preview",
                        "media_url": f"{download_url}/media",
                        "thumbnail_url": (
                            f"{download_url}/thumbnail"
                            if preview.kind in {"image", "video"}
                            else ""
                        ),
                    }
                )
        views[reference.id] = view
    return views


def _citation_pages(grant) -> dict[int, int]:
    return {
        int(entry.citation[1:]): math.ceil(index / _GUEST_PAGE_SIZE)
        for index, entry in enumerate(_guest_entries(grant, ""), start=1)
        if entry.citation.startswith("S") and entry.citation[1:].isdigit()
    }


def _normalize_answer_markdown(content: str) -> str:
    expanded: list[str] = []
    for line in (content or "").splitlines():
        if ": - " in line:
            lead, inline_items = line.split(": - ", 1)
            items = [
                item.strip()
                for item in inline_items.split(" - ")
                if item.strip()
            ]
            if len(items) > 1:
                expanded.extend(
                    (f"{lead.rstrip()}:", "", *(f"- {item}" for item in items))
                )
                continue
        expanded.append(line)

    normalized: list[str] = []
    in_list = False
    for line in expanded:
        is_list_item = bool(re.match(r"^\s*(?:[-*+]|\d+\.)\s+\S", line))
        if is_list_item and not in_list and normalized and normalized[-1].strip():
            normalized.append("")
        elif in_list and line.strip() and not is_list_item:
            normalized.append("")
        normalized.append(line)
        in_list = is_list_item
    return "\n".join(normalized)


def _answer_html(
    content: str,
    citation_pages: dict[int, int] | None = None,
    evidence_base: str = "/share/session",
):
    pages = citation_pages or {}

    def evidence_target(citation: int) -> str:
        page = pages.get(
            citation,
            math.ceil(citation / _GUEST_PAGE_SIZE),
        )
        return f"{evidence_base}?page={page}#evidence-{citation}"

    def natural_evidence_link(match: re.Match[str]) -> str:
        phrase = match.group(1).strip()
        citation = int(match.group(2))
        escaped_phrase = phrase.replace("\\", "\\\\").replace("[", r"\[")
        return f"[{escaped_phrase}]({evidence_target(citation)})"

    def fallback_evidence_link(match: re.Match[str]) -> str:
        citation = int(match.group(1))
        return (
            r" [\[See entry\]]"
            f"({evidence_target(citation)})"
        )

    linked = _NATURAL_EVIDENCE.sub(
        natural_evidence_link,
        _normalize_answer_markdown(content),
    )
    linked = _EVIDENCE.sub(fallback_evidence_link, linked)
    return render_markdown(linked)


def _guest_context(
    request: Request,
    grant,
    session_id: str,
    *,
    query: str = "",
    selected_tags: tuple[str, ...] = (),
    page: int = 1,
    error: str = "",
    owner_preview: bool = False,
) -> dict[str, Any]:
    tag_counts: Counter[str] = Counter()
    tag_labels: dict[str, str] = {}
    for entry in grant.snapshot.entries:
        entry_tags: set[str] = set()
        for tag in entry.tags:
            key = tag.casefold()
            tag_labels.setdefault(key, tag)
            entry_tags.add(key)
        tag_counts.update(entry_tags)
    available_tags = tuple(
        sorted(
            (
                (tag_labels[key], count)
                for key, count in tag_counts.items()
            ),
            key=lambda item: (-item[1], item[0].casefold()),
        )
    )
    canonical_tags = {
        tag.casefold(): tag
        for tag, _ in available_tags
    }
    selected_tags = tuple(
        canonical_tags.get(tag.casefold(), tag)
        for tag in _normalized_guest_tags(selected_tags)
    )
    unavailable_selected_tags = tuple(
        tag
        for tag in selected_tags
        if tag.casefold() not in canonical_tags
    )
    matches = _guest_entries(grant, query, selected_tags)
    total_pages = max(1, math.ceil(len(matches) / _GUEST_PAGE_SIZE))
    page = min(max(1, page), total_pages)
    start = (page - 1) * _GUEST_PAGE_SIZE
    store = get_share_store()
    messages = [
        {
            "role": message.role,
            "content": message.content,
            "html": _answer_html(message.content, _citation_pages(grant)),
            "created_at": _format_utc(message.created_at),
        }
        for message in store.list_chat_messages(session_id, grant.id)
    ]
    recipient = grant.snapshot.recipient.strip() or "there"
    owner_profile = _profile()
    reference_base = (
        f"/sharing/shares/{grant.id}/preview/references"
        if owner_preview
        else "/share/session/references"
    )
    return {
        "request": request,
        "grant": grant,
        "entries": tuple(
            {
                "entry": entry,
                "html": _entry_html(entry),
                "reference_views": _reference_views(
                    entry,
                    base_url=reference_base,
                ),
            }
            for entry in matches[start : start + _GUEST_PAGE_SIZE]
        ),
        "result_count": len(matches),
        "page": page,
        "total_pages": total_pages,
        "page_size": _GUEST_PAGE_SIZE,
        "query": query,
        "selected_tags": selected_tags,
        "available_tags": available_tags,
        "unavailable_selected_tags": unavailable_selected_tags,
        "messages": messages,
        "error": error,
        "suggested_prompts": suggested_prompts(
            grant.snapshot,
            owner_profile.display_name,
        ),
        "expires_at_display": _expiry_display(grant),
        "content_refreshed_at": _format_utc(grant.snapshot.created_at),
        "recipient": recipient,
        "recipient_initial": recipient[0].upper(),
        "share_recipient": grant.snapshot.recipient.strip(),
        "owner_preview": owner_preview,
        "owner_profile": owner_profile,
        "owner_name": owner_profile.display_name,
    }


@guest_router.get("/session", response_class=HTMLResponse)
async def guest_portal(
    request: Request,
    q: str = "",
    page: int = 1,
    fragment: bool = False,
):
    session = current_session(request, get_share_store())
    if not session:
        return _unavailable(request)
    grant, session_id = session
    if len(q) > _MAX_GUEST_SEARCH_CHARS:
        raise HTTPException(
            status_code=422,
            detail="Search queries must be 500 characters or fewer.",
        )
    grant = _refresh_live_grant(grant)
    selected_tags = tuple(request.query_params.getlist("tag"))
    context = _guest_context(
        request,
        grant,
        session_id,
        query=q,
        selected_tags=selected_tags,
        page=page,
    )
    response = templates.TemplateResponse(
        request,
        (
            "modules/hfl_shares/_guest_entries.html"
            if fragment
            else "modules/hfl_shares/guest.html"
        ),
        context,
    )
    if fragment:
        response.headers["X-HFL-Result-Count"] = str(context["result_count"])
    response.headers["Cache-Control"] = "no-store"
    return response


@guest_router.get("/session/manifesto", response_class=HTMLResponse)
async def guest_manifesto(request: Request):
    session = current_session(request, get_share_store())
    if not session:
        return HTMLResponse(
            '<p class="notice error">This shared Manifesto is no longer available.</p>',
            status_code=404,
            headers={"Cache-Control": "no-store"},
        )
    return _manifesto_fragment(request)


@guest_router.post("/session/chat", response_class=HTMLResponse)
async def guest_chat(request: Request):
    store = get_share_store()
    session = current_session(request, store)
    if not session:
        return _unavailable(request)
    grant, session_id = session
    form = await _guest_form(request)
    wants_json = (
        "application/json" in request.headers.get("accept", "")
        or str(form.get("_async") or "") == "1"
    )
    try:
        question = _validated_question(form.get("question"))
        grant = _refresh_live_grant(grant)
        if not store.allow_chat(
            grant.id, get_settings().hfl_share_chat_limit_per_hour
        ):
            raise ValueError(
                "This share has reached its hourly question limit."
            )
        history_messages = store.list_chat_messages(
            session_id,
            grant.id,
            limit=8,
        )
        history = tuple(
            {"role": item.role, "content": item.content}
            for item in history_messages
        )
        user_message = store.add_chat_message(
            session_id=session_id,
            share_id=grant.id,
            role="user",
            content=question,
        )
        answer = await answer_question(
            grant.snapshot,
            question,
            history=history,
            share_id=grant.id,
        )
        assistant_message = store.add_chat_message(
            session_id=session_id,
            share_id=grant.id,
            role="assistant",
            content=answer,
        )
        record_share_audit(
            event="question-answered",
            share_id=grant.id,
            question=question,
            answer=answer,
        )
        error = ""
    except (AgentUnavailable, ValueError) as exc:
        error = str(exc)
    if wants_json:
        if error:
            return JSONResponse({"detail": error}, status_code=422)
        return JSONResponse(
            {
                "user": {
                    "content": user_message.content,
                    "created_at": _format_utc(user_message.created_at),
                },
                "assistant": {
                    "content": assistant_message.content,
                    "html": str(
                        _answer_html(
                            assistant_message.content,
                            _citation_pages(grant),
                        )
                    ),
                    "created_at": _format_utc(assistant_message.created_at),
                },
            }
        )
    return templates.TemplateResponse(
        request,
        "modules/hfl_shares/guest.html",
        _guest_context(
            request,
            grant,
            session_id,
            error=error,
        ),
        status_code=422 if error else 200,
    )


def _enabled_reference(grant, reference_id: str):
    return next(
        (
            reference
            for entry in grant.snapshot.entries
            for reference in entry.references
            if reference.id == reference_id and reference.enabled
        ),
        None,
    )


def _preview_file(grant, reference_id: str):
    reference = _enabled_reference(grant, reference_id)
    if not reference or reference.kind == "external":
        raise HTTPException(status_code=404, detail="Reference unavailable.")
    path = Path(reference.target)
    roots = allowed_reference_roots(resolve_corpus_root())
    if not path.is_file() or not is_within_roots(path, roots):
        raise HTTPException(status_code=404, detail="Reference unavailable.")
    preview = classify_preview(path)
    if not preview:
        raise HTTPException(
            status_code=415,
            detail="This file is not available for inline preview.",
        )
    return reference, path, preview


def _download_response(grant, reference_id: str):
    reference = _enabled_reference(grant, reference_id)
    if not reference:
        raise HTTPException(status_code=404, detail="Reference unavailable.")
    if reference.kind == "external":
        parsed = urlparse(reference.target)
        if (
            parsed.scheme != "https"
            or not parsed.netloc
            or parsed.username
            or parsed.password
        ):
            raise HTTPException(status_code=404, detail="Reference unavailable.")
        record_share_audit(event="reference-opened", share_id=grant.id)
        return RedirectResponse(reference.target, status_code=302)
    path = Path(reference.target)
    roots = allowed_reference_roots(resolve_corpus_root())
    if not path.is_file() or not is_within_roots(path, roots):
        raise HTTPException(status_code=404, detail="Reference unavailable.")
    record_share_audit(event="reference-downloaded", share_id=grant.id)
    return FileResponse(path, filename=reference.label)


def _preview_fragment(grant, reference_id: str) -> HTMLResponse:
    _, path, preview = _preview_file(grant, reference_id)
    if preview.kind in {"image", "video"}:
        record_share_audit(event="reference-previewed", share_id=grant.id)
        return HTMLResponse("", status_code=204, headers={"Cache-Control": "no-store"})
    try:
        source = read_preview_text(path)
    except (OSError, UnicodeDecodeError, ValueError):
        raise HTTPException(
            status_code=422,
            detail="This text file could not be safely displayed.",
        ) from None
    record_share_audit(event="reference-previewed", share_id=grant.id)
    if preview.kind == "markdown":
        content = f'<div class="viewer-document markdown-body">{render_markdown(source)}</div>'
    else:
        content = (
            '<pre class="viewer-document viewer-plain-text">'
            f"{html.escape(source)}"
            "</pre>"
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


def _media_response(
    request: Request,
    grant,
    reference_id: str,
):
    reference, path, preview = _preview_file(grant, reference_id)
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
            headers={
                **headers,
                "Content-Range": f"bytes */{preview.size}",
            },
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
        filename=reference.label,
        media_type=preview.media_type,
        content_disposition_type="inline",
        headers=headers,
    )


def _thumbnail_response(grant, reference_id: str):
    _, path, preview = _preview_file(grant, reference_id)
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


def _owner_preview_grant(request: Request, share_id: str):
    _, redirect = require_user(request)
    if redirect:
        raise HTTPException(status_code=401, detail="Authentication required.")
    grant = get_share_store().get_share(share_id)
    if not grant or not grant.available:
        raise HTTPException(status_code=404, detail="Active share not found.")
    return grant


@owner_router.get("/shares/{share_id}/preview/references/{reference_id}")
def owner_preview_reference(
    request: Request,
    share_id: str,
    reference_id: str,
):
    return _download_response(_owner_preview_grant(request, share_id), reference_id)


@owner_router.get("/shares/{share_id}/preview/references/{reference_id}/preview")
def owner_preview_reference_text(
    request: Request,
    share_id: str,
    reference_id: str,
):
    return _preview_fragment(_owner_preview_grant(request, share_id), reference_id)


@owner_router.get("/shares/{share_id}/preview/references/{reference_id}/media")
def owner_preview_reference_media(
    request: Request,
    share_id: str,
    reference_id: str,
):
    return _media_response(
        request,
        _owner_preview_grant(request, share_id),
        reference_id,
    )


@owner_router.get("/shares/{share_id}/preview/references/{reference_id}/thumbnail")
def owner_preview_reference_thumbnail(
    request: Request,
    share_id: str,
    reference_id: str,
):
    return _thumbnail_response(
        _owner_preview_grant(request, share_id),
        reference_id,
    )


@guest_router.get("/session/references/{reference_id}")
def guest_reference(request: Request, reference_id: str):
    grant = current_grant(request, get_share_store())
    if not grant:
        return _unavailable(request)
    return _download_response(grant, reference_id)


@guest_router.get("/session/references/{reference_id}/preview")
def guest_reference_text(request: Request, reference_id: str):
    grant = current_grant(request, get_share_store())
    if not grant:
        raise HTTPException(status_code=404, detail="Reference unavailable.")
    return _preview_fragment(grant, reference_id)


@guest_router.get("/session/references/{reference_id}/media")
def guest_reference_media(request: Request, reference_id: str):
    grant = current_grant(request, get_share_store())
    if not grant:
        raise HTTPException(status_code=404, detail="Reference unavailable.")
    return _media_response(request, grant, reference_id)


@guest_router.get("/session/references/{reference_id}/thumbnail")
def guest_reference_thumbnail(request: Request, reference_id: str):
    grant = current_grant(request, get_share_store())
    if not grant:
        raise HTTPException(status_code=404, detail="Reference unavailable.")
    return _thumbnail_response(grant, reference_id)


@guest_router.post("/session/logout")
async def guest_logout(request: Request):
    store = get_share_store()
    session = current_session(request, store)
    if session:
        store.revoke_session(session[1])
        record_share_audit(event="session-closed", share_id=session[0].id)
    response = RedirectResponse("/share/unavailable", status_code=303)
    clear_guest_cookie(response)
    return response


@guest_router.get("/unavailable", response_class=HTMLResponse)
async def unavailable_page(request: Request):
    return _unavailable(request)
