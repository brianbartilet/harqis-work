"""Owner and guest routes for temporary Activity Corpus sharing."""

from __future__ import annotations

import hmac
import secrets
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse

from config import get_settings
from modules.hfl_corpus.corpus import (
    common_sources,
    common_tags,
    corpus_index,
    resolve_corpus_root,
)
from modules.hfl_shares.agent import AgentUnavailable, answer_question
from modules.hfl_shares.audit import record_share_audit
from modules.hfl_shares.models import ShareConfiguration, parse_csv
from modules.hfl_shares.scope import (
    build_snapshot,
    suggested_prompts,
)
from modules.hfl_shares.security import (
    REQUEST_COOKIE,
    clear_guest_cookie,
    current_grant,
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
    verify_csrf_token,
    verify_pin,
)
from modules.hfl_shares.store import get_share_store
from services.safe_paths import allowed_reference_roots, is_within_roots
from web import page_context, require_user, templates


owner_router = APIRouter(prefix="/sharing")
guest_router = APIRouter(prefix="/share")


def _sharing_documents(*, force: bool = False):
    if get_settings().hfl_corpus_api_url.strip():
        raise ValueError(
            "Sharing is available only on the canonical Activity Corpus host."
        )
    return corpus_index.documents(force=force)


def _configuration_from_form(
    form: Any,
    *,
    existing: ShareConfiguration | None = None,
) -> ShareConfiguration:
    settings = get_settings()
    ttl_minutes = int(
        str(
            form.get("ttl_minutes")
            or max(5, settings.hfl_share_default_ttl_seconds // 60)
        )
    )
    device_limit = int(
        str(form.get("device_limit") or settings.hfl_share_default_device_limit)
    )
    return ShareConfiguration(
        id=str(form.get("configuration_id") or ""),
        name=str(form.get("name") or "").strip(),
        description=str(form.get("description") or "").strip(),
        sources=tuple(str(item) for item in form.getlist("sources") if str(item)),
        tags=parse_csv(str(form.get("tags") or "")),
        date_from=str(form.get("date_from") or "").strip(),
        date_to=str(form.get("date_to") or "").strip(),
        topic=str(form.get("topic") or "").strip(),
        selected_entry_ids=parse_csv(
            str(form.get("selected_entry_ids") or "")
        ),
        test_prompts=tuple(
            line.strip()
            for line in str(form.get("test_prompts") or "").splitlines()
            if line.strip()
        ),
        auth_mode=str(form.get("auth_mode") or "pin"),
        allowed_email=str(form.get("allowed_email") or "").strip(),
        references_enabled=form.get("references_enabled") == "on",
        ttl_seconds=ttl_minutes * 60,
        device_limit=device_limit,
        single_use=form.get("single_use") == "on",
        created_at=existing.created_at if existing else "",
        updated_at=existing.updated_at if existing else "",
    )


def _require_csrf(form: Any, user: str) -> None:
    if not verify_csrf_token(str(form.get("csrf") or ""), user):
        raise HTTPException(status_code=403, detail="Invalid form token.")


def _owner_context(
    request: Request,
    user: str,
    *,
    configuration: ShareConfiguration | None = None,
    preview=None,
    preview_answer: str = "",
    preview_question: str = "",
    error: str = "",
) -> dict[str, Any]:
    try:
        documents = _sharing_documents()
        corpus_error = ""
    except ValueError as exc:
        documents = ()
        corpus_error = str(exc)
    store = get_share_store()
    sources = set(common_sources(documents))
    if configuration:
        sources.update(configuration.sources)
    return page_context(
        request,
        user,
        "sharing",
        configurations=store.list_configurations(),
        shares=store.list_shares(),
        pending_requests=store.list_pending_requests(),
        available_sources=tuple(sorted(sources, key=str.casefold)),
        available_tags=common_tags(documents, limit=100),
        configuration=configuration,
        preview=preview,
        preview_answer=preview_answer,
        preview_question=preview_question,
        suggested_prompts=suggested_prompts(preview) if preview else (),
        error=error or corpus_error,
        csrf=make_csrf_token(user),
        defaults=get_settings(),
    )


@owner_router.get("", response_class=HTMLResponse)
async def sharing_page(
    request: Request,
    configuration_id: str = "",
    duplicate: bool = False,
):
    user, redirect = require_user(request)
    if redirect:
        return redirect
    configuration = None
    if configuration_id:
        configuration = get_share_store().get_configuration(configuration_id)
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
    return templates.TemplateResponse(
        request,
        "modules/hfl_shares/index.html",
        _owner_context(request, user, configuration=configuration),
    )


@owner_router.post("/configurations", response_class=HTMLResponse)
async def save_configuration(request: Request):
    user, redirect = require_user(request)
    if redirect:
        return redirect
    form = await request.form()
    _require_csrf(form, user)
    store = get_share_store()
    existing = store.get_configuration(str(form.get("configuration_id") or ""))
    try:
        configuration = _configuration_from_form(form, existing=existing)
        saved = store.save_configuration(configuration)
    except (TypeError, ValueError) as exc:
        return templates.TemplateResponse(
            request,
            "modules/hfl_shares/index.html",
            _owner_context(request, user, error=str(exc)),
            status_code=422,
        )
    return RedirectResponse(
        f"/sharing?configuration_id={saved.id}", status_code=303
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


async def _preview_response(
    request: Request,
    user: str,
    *,
    with_agent: bool,
) -> HTMLResponse:
    form = await request.form()
    _require_csrf(form, user)
    store = get_share_store()
    existing = store.get_configuration(str(form.get("configuration_id") or ""))
    try:
        configuration = _configuration_from_form(form, existing=existing)
        preview = build_snapshot(
            configuration,
            _sharing_documents(),
            enabled_reference_ids=tuple(
                str(item) for item in form.getlist("enabled_reference_ids")
            ),
        )
        question = str(form.get("question") or "").strip()
        answer = ""
        if with_agent:
            answer = await answer_question(preview, question)
    except (AgentUnavailable, TypeError, ValueError) as exc:
        return templates.TemplateResponse(
            request,
            "modules/hfl_shares/index.html",
            _owner_context(
                request,
                user,
                configuration=locals().get("configuration"),
                preview=locals().get("preview"),
                preview_question=str(form.get("question") or ""),
                error=str(exc),
            ),
            status_code=422,
        )
    return templates.TemplateResponse(
        request,
        "modules/hfl_shares/index.html",
        _owner_context(
            request,
            user,
            configuration=configuration,
            preview=preview,
            preview_answer=answer,
            preview_question=question,
        ),
    )


@owner_router.post("/preview", response_class=HTMLResponse)
async def preview_scope(request: Request):
    user, redirect = require_user(request)
    if redirect:
        return redirect
    return await _preview_response(request, user, with_agent=False)


@owner_router.post("/preview/chat", response_class=HTMLResponse)
async def preview_chat(request: Request):
    user, redirect = require_user(request)
    if redirect:
        return redirect
    return await _preview_response(request, user, with_agent=True)


@owner_router.post("/generate", response_class=HTMLResponse)
async def generate_share(request: Request):
    user, redirect = require_user(request)
    if redirect:
        return redirect
    form = await request.form()
    _require_csrf(form, user)
    store = get_share_store()
    existing = store.get_configuration(str(form.get("configuration_id") or ""))
    try:
        configuration = _configuration_from_form(form, existing=existing)
        enabled_references = tuple(
            str(item) for item in form.getlist("enabled_reference_ids")
        )
        snapshot = build_snapshot(
            configuration,
            _sharing_documents(force=True),
            enabled_reference_ids=enabled_references,
        )
        if not snapshot.entries:
            raise ValueError("A share cannot be generated from an empty scope.")
        settings = get_settings()
        if len(snapshot.entries) > settings.hfl_share_max_snapshot_entries:
            raise ValueError(
                "The scope is too broad to share. Narrow it below "
                f"{settings.hfl_share_max_snapshot_entries} entries."
            )
        if snapshot.estimated_chars > settings.hfl_share_max_snapshot_chars:
            raise ValueError(
                "The scope is too large to share. Narrow its sources or filters."
            )
        public_token = new_public_token()
        pin = new_pin() if configuration.auth_mode == "pin" else ""
        base = get_settings().hfl_share_public_url.strip().rstrip("/")
        if not base:
            base = str(request.base_url).rstrip("/")
        parsed_base = urlparse(base)
        if get_settings().behind_proxy and parsed_base.scheme != "https":
            raise ValueError(
                "HFL_SHARE_PUBLIC_URL must be an HTTPS URL when the frontend "
                "is behind a proxy."
            )
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
            ttl_seconds=configuration.ttl_seconds,
            single_use=configuration.single_use,
            device_limit=configuration.device_limit,
        )
        generated = {
            "grant": grant,
            "link": link,
            "pin": pin,
            "qr": qr,
        }
        record_share_audit(event="created", share_id=grant.id)
    except (TypeError, ValueError) as exc:
        return templates.TemplateResponse(
            request,
            "modules/hfl_shares/index.html",
            _owner_context(
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


@guest_router.get("/access/{token}", response_class=HTMLResponse)
@guest_router.get("/email/{token}", response_class=HTMLResponse)
async def share_access(request: Request, token: str):
    grant = get_share_store().get_share_by_token_hash(opaque_hash(token))
    if not grant or not grant.available:
        return _unavailable(request)
    return templates.TemplateResponse(
        request,
        "modules/hfl_shares/access.html",
        {"request": request, "grant": grant, "token": token, "error": ""},
    )


@guest_router.post("/access/{token}/redeem")
@guest_router.post("/email/{token}/redeem")
async def redeem_share(request: Request, token: str):
    store = get_share_store()
    grant = store.get_share_by_token_hash(opaque_hash(token))
    if not grant or not grant.available:
        return _unavailable(request)
    form = await request.form()
    if grant.auth_mode == "pin":
        if grant.pin_failures >= get_settings().hfl_share_pin_max_attempts:
            return _unavailable(request, status_code=429)
        if not verify_pin(
            str(form.get("pin") or ""), store.pin_hash_for_share(grant.id)
        ):
            store.record_pin_failure(grant.id)
            record_share_audit(event="failed-redemption", share_id=grant.id)
            return templates.TemplateResponse(
                request,
                "modules/hfl_shares/access.html",
                {
                    "request": request,
                    "grant": grant,
                    "token": token,
                    "error": "The access details were not accepted.",
                },
                status_code=403,
            )
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
        return _unavailable(request, status_code=403)
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
        issued = issue_session(store, access_request["share_id"])
        if not issued:
            return _unavailable(request, status_code=403)
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


def _guest_entries(grant, query: str):
    needle = (query or "").strip().casefold()
    if not needle:
        return grant.snapshot.entries
    return tuple(
        entry
        for entry in grant.snapshot.entries
        if needle
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


def _guest_context(
    request: Request,
    grant,
    *,
    query: str = "",
    question: str = "",
    answer: str = "",
    error: str = "",
) -> dict[str, Any]:
    return {
        "request": request,
        "grant": grant,
        "entries": _guest_entries(grant, query),
        "query": query,
        "question": question,
        "answer": answer,
        "error": error,
        "suggested_prompts": suggested_prompts(grant.snapshot),
    }


@guest_router.get("/session", response_class=HTMLResponse)
async def guest_portal(request: Request, q: str = ""):
    grant = current_grant(request, get_share_store())
    if not grant:
        return _unavailable(request)
    return templates.TemplateResponse(
        request,
        "modules/hfl_shares/guest.html",
        _guest_context(request, grant, query=q),
    )


@guest_router.post("/session/chat", response_class=HTMLResponse)
async def guest_chat(request: Request):
    store = get_share_store()
    grant = current_grant(request, store)
    if not grant:
        return _unavailable(request)
    form = await request.form()
    question = str(form.get("question") or "").strip()
    try:
        if not store.allow_chat(
            grant.id, get_settings().hfl_share_chat_limit_per_hour
        ):
            raise ValueError(
                "This share has reached its hourly question limit."
            )
        answer = await answer_question(grant.snapshot, question)
        record_share_audit(
            event="question-answered",
            share_id=grant.id,
            question=question,
            answer=answer,
        )
        error = ""
    except (AgentUnavailable, ValueError) as exc:
        answer = ""
        error = str(exc)
    return templates.TemplateResponse(
        request,
        "modules/hfl_shares/guest.html",
        _guest_context(
            request,
            grant,
            question=question,
            answer=answer,
            error=error,
        ),
        status_code=422 if error else 200,
    )


@guest_router.get("/session/references/{reference_id}")
async def guest_reference(request: Request, reference_id: str):
    grant = current_grant(request, get_share_store())
    if not grant:
        return _unavailable(request)
    reference = next(
        (
            reference
            for entry in grant.snapshot.entries
            for reference in entry.references
            if reference.id == reference_id and reference.enabled
        ),
        None,
    )
    if not reference:
        return _unavailable(request)
    if reference.kind == "external":
        parsed = urlparse(reference.target)
        if (
            parsed.scheme != "https"
            or not parsed.netloc
            or parsed.username
            or parsed.password
        ):
            return _unavailable(request)
        record_share_audit(event="reference-opened", share_id=grant.id)
        return RedirectResponse(reference.target, status_code=302)
    path = Path(reference.target)
    roots = allowed_reference_roots(resolve_corpus_root())
    if not path.is_file() or not is_within_roots(path, roots):
        return _unavailable(request)
    record_share_audit(event="reference-downloaded", share_id=grant.id)
    return FileResponse(path, filename=reference.label)


@guest_router.post("/session/logout")
async def guest_logout(request: Request):
    response = RedirectResponse("/share/unavailable", status_code=303)
    clear_guest_cookie(response)
    return response


@guest_router.get("/unavailable", response_class=HTMLResponse)
async def unavailable_page(request: Request):
    return _unavailable(request)
