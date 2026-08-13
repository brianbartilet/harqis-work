"""Routes for browsing, searching, and adding entries to the HFL corpus."""

import asyncio
import base64
import html
import json
import logging
import re
from dataclasses import replace
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
    build_tree,
    common_tags,
    common_sources,
    corpus_index,
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
from modules.hfl_corpus.document_edit import UpdateDocumentRequest, update_document_text
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
from modules.profile.store import get_profile_store
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
_H2 = re.compile(r"<h2(?:\s+[^>]*)?>")
_log = logging.getLogger(__name__)


class SecretPinRequest(BaseModel):
    pin: str


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


def _anchor_rendered_entries(rendered: Markup, document) -> Markup:
    anchors = iter(entry.anchor for entry in document.entries)

    def replace(match: re.Match) -> str:
        anchor = next(anchors, "")
        return f'<h2 id="{anchor}" class="scroll-mt-40">' if anchor else match.group(0)

    return Markup(_H2.sub(replace, str(rendered)))


def _uses_remote_corpus() -> bool:
    return bool(get_settings().hfl_corpus_api_url.strip())


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
    return "/hfl-corpus" + (f"?{urlencode(params)}" if params else "")


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
):
    user, redirect = require_user(request)
    if redirect:
        return redirect
    if date_field not in {"created", "updated"}:
        date_field = "created"
    if sort not in {"asc", "desc"}:
        sort = "desc"
    # Preserve old bookmarked URLs while presenting only the simplified UI.
    if not date_from and not date_to:
        if updated_from or updated_to:
            date_field, date_from, date_to = "updated", updated_from, updated_to
        elif created_from or created_to:
            date_field, date_from, date_to = "created", created_from, created_to
    profile = get_profile_store().get()
    protected_tags = normalize_secret_tags(profile.secret_tags)
    authorized = secrets_unlocked(request, profile)
    include_secrets = bool(show_secrets and authorized)
    remote_error = ""
    if _uses_remote_corpus():
        try:
            remote = RemoteCorpusClient.from_settings().index(params={
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
            })
            documents = remote["documents"]
            tree = remote["tree"]
            results = remote["results"]
            total_results = remote["total_results"]
            document_count = remote["document_count"]
            tag_cloud = remote["tag_cloud"]
            source_options = remote.get("sources", [])
            selected_source = remote.get("selected_source", "")
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
            result_page = paginate_documents((), page=page, page_size=page_size)
            remote_error = str(exc)
    else:
        raw_documents = corpus_index.documents()
        tag_cloud = common_tags(raw_documents)
        documents = raw_documents if include_secrets else filter_documents(
            raw_documents, protected_tags
        )
        source_options = common_sources(documents)
        selected_source = normalize_source(source, source_options)
        tree = shallow_tree(build_tree(documents))
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
    }
    previous_page_url = _index_url(
        **page_url_values, page=result_page.page - 1
    )
    next_page_url = _index_url(
        **page_url_values, page=result_page.page + 1
    )
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
            result = RemoteCorpusClient.from_settings().create_entry(
                payload.model_dump()
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
            branch = RemoteCorpusClient.from_settings().tree(
                path, include_secrets=include_secrets, secret_tags=protected_tags
            )
        except RemoteCorpusError as exc:
            return HTMLResponse(str(exc), status_code=502)
    else:
        documents = corpus_index.documents()
        if not include_secrets:
            documents = filter_documents(documents, protected_tags)
        tree = build_tree(documents)
        node = find_tree_node(tree, path)
        if not node:
            return HTMLResponse("Corpus directory not found", status_code=404)
        branch = shallow_tree(node)
    return templates.TemplateResponse(
        request,
        "modules/hfl_corpus/partials/tree.html",
        {"tree": branch, "show_secrets": include_secrets},
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
            match_page = RemoteCorpusClient.from_settings().matches(
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
        selected_source = normalize_source(
            source,
            common_sources(corpus_index.documents()),
        )
        visible_documents = (document,) if include_secrets else filter_documents(
            (document,), protected_tags
        )
        matching_entries = (
            visible_documents[0].matching_entries(
                selected_tags, text_query, selected_source
            )
            if visible_documents else ()
        )
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
            document, references = RemoteCorpusClient.from_settings().document(
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
        visible = not secret or (authorized and (show_secrets or reveal == entry.anchor))
        if visible:
            entry_rendered = render_markdown(
                format_hfl_markdown(f"## {entry.text}", references)
            )
            rendered_parts.append(
                str(_anchor_rendered_entries(entry_rendered, replace(document, entries=(entry,))))
            )
        else:
            anchor = html.escape(entry.anchor, quote=True)
            rendered_parts.append(
                f'<section id="{anchor}" class="secret-entry-placeholder scroll-mt-40" '
                f'data-secret-entry="{anchor}"><div><strong>Secret entry</strong>'
                '<p>Protected content is hidden.</p></div>'
                f'<button type="button" data-secret-reveal="{anchor}">Show</button></section>'
            )
    rendered = (
        Markup("\n".join(rendered_parts))
        if has_secrets
        else _anchor_rendered_entries(
            render_markdown(format_hfl_markdown(document.text, references)), document
        )
    )
    filtered = filter_documents((document,), protected_tags)
    display_document = document if show_secrets and authorized else (
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
        existing_document = (
            RemoteCorpusClient.from_settings().document(
                relative_path, include_secrets=True, secret_tags=protected_tags
            )[0]
            if _uses_remote_corpus()
            else corpus_index.get(relative_path)
        )
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
        )
        corpus_index.documents(force=True)
        return {
            "updated": True,
            "relative_path": document.relative_path,
            "size": path.stat().st_size,
        }
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
        content, filename, media_type = RemoteCorpusClient.from_settings().download(token)
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
        content, status_code, headers = (
            RemoteCorpusClient.from_settings().reference_content(
                token,
                endpoint,
                range_header=request.headers.get("range", ""),
            )
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
