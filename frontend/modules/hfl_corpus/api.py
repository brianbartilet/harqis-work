"""Authenticated read and manual-entry API for the canonical HFL corpus host."""

from __future__ import annotations

import asyncio
import html
import hmac
import logging
from dataclasses import replace
from dataclasses import asdict

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, HTMLResponse
from pydantic import ValidationError

from config import get_settings
from modules.hfl_corpus.corpus import (
    CorpusDocument,
    corpus_index,
    find_tree_node,
    paginate_documents,
    parse_search_query,
    normalize_source,
    resolve_corpus_root,
    search_documents,
    shallow_tree,
)
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
    filter_document,
    is_secret_entry,
    normalize_secret_tags,
)
from modules.hfl_corpus.view import corpus_view_cache
from modules.hfl_shares.viewer import (
    classify_preview,
    read_preview_text,
    thumbnail_path,
)
from services.markdown import render_markdown
from services.safe_paths import (
    allowed_reference_roots,
    load_download_token,
    resolve_reference,
)


router = APIRouter(prefix="/api/hfl", tags=["hfl-corpus-api"])
_log = logging.getLogger(__name__)


def _authorize(request: Request) -> None:
    expected = get_settings().hfl_corpus_api_token.strip()
    if not expected:
        raise HTTPException(status_code=503, detail="HFL corpus API token is not configured")
    scheme, _, supplied = request.headers.get("Authorization", "").partition(" ")
    if scheme.casefold() != "bearer" or not hmac.compare_digest(supplied, expected):
        raise HTTPException(status_code=401, detail="Invalid HFL corpus API token")


def _preview_reference_path(token: str):
    root = resolve_corpus_root()
    path = load_download_token(token, allowed_reference_roots(root))
    if not path:
        raise HTTPException(status_code=404, detail="Reference unavailable")
    preview = classify_preview(path)
    if not preview:
        raise HTTPException(
            status_code=415,
            detail="This file is not available for inline preview.",
        )
    return path, preview


def _document_payload(
    document: CorpusDocument,
    *,
    include_text: bool = False,
    include_entries: bool = False,
    matching_entry_count: int | None = None,
    include_tag_entry_anchors: bool = False,
) -> dict:
    payload = {
        "relative_path": document.relative_path,
        "name": document.name,
        "created_at": document.created_at.isoformat(),
        "updated_at": document.updated_at.isoformat(),
        "tags": list(document.tags),
        "tag_counts": [list(item) for item in document.tag_counts],
        "entry_count": document.entry_count,
        "excerpt": document.excerpt,
    }
    if include_entries:
        payload["entries"] = [asdict(entry) for entry in document.entries]
    if matching_entry_count is not None:
        payload["matching_entry_count"] = matching_entry_count
    if include_tag_entry_anchors:
        anchors = {
            tag.casefold(): anchor
            for tag, anchor in document.tag_entry_anchors
        }
        tag_entry_anchors = []
        for tag in document.tags:
            anchor = anchors.get(tag.casefold())
            if anchor is None:
                anchor = document.first_matching_entry_anchor(tag)
            if anchor:
                tag_entry_anchors.append([tag, anchor])
        payload["tag_entry_anchors"] = tag_entry_anchors
    if include_text:
        payload["text"] = document.text
    return payload


def _tree_payload(node: dict) -> dict:
    return {
        "name": node["name"],
        "path": node["path"],
        "directories": [_tree_payload(directory) for directory in node["directories"]],
        "files": [_document_payload(document) for document in node["files"]],
    }


@router.post("/entries")
async def hfl_api_create_entry(
    request: Request,
    payload: CreateEntryRequest,
):
    _authorize(request)
    try:
        result = persist_manual_entry(payload, corpus_dir=resolve_corpus_root())
        corpus_index.documents(force=True)
        return result
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail="The entry could not be saved.",
        ) from exc


@router.post("/entries/preview")
async def hfl_api_preview_entry(
    request: Request,
    payload: CreateEntryRequest,
):
    _authorize(request)
    try:
        enriched, enrichment = await asyncio.to_thread(enrich_manual_entry, payload)
        return preview_manual_entry(enriched, enrichment=enrichment)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/entries/upload", dependencies=[Depends(_authorize)])
async def hfl_api_upload_entry(
    payload: str = Form(...),
    files: list[UploadFile] = File(default=[]),
):
    try:
        entry_payload = CreateEntryRequest.model_validate_json(payload)
        result = await persist_manual_entry_with_uploads(
            entry_payload,
            files,
            corpus_dir=resolve_corpus_root(),
        )
        corpus_index.documents(force=True)
        return result
    except (ValueError, ValidationError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        _log.exception("Canonical HFL manual entry upload failed")
        raise HTTPException(
            status_code=500,
            detail="The entry and files could not be saved.",
        ) from exc


@router.get("/documents")
async def hfl_api_documents(
    request: Request,
    q: str = "",
    date_field: str = "created",
    date_from: str = "",
    date_to: str = "",
    sort: str = "desc",
    page: int = 1,
    page_size: int = 20,
    compact: bool = False,
    source: str = "",
    include_secrets: bool = False,
    secret_tags: str = "",
):
    _authorize(request)
    if date_field not in {"created", "updated"}:
        date_field = "created"
    if sort not in {"asc", "desc"}:
        sort = "desc"
    raw_documents = corpus_index.documents()
    protected_tags = normalize_secret_tags(secret_tags)
    view = corpus_view_cache.get(
        raw_documents,
        include_secrets=include_secrets,
        secret_tags=protected_tags,
    )
    documents = view.documents
    sources = view.sources
    selected_source = normalize_source(source, sources)
    results = search_documents(
        documents,
        query=q,
        date_field=date_field,
        date_from=date_from,
        date_to=date_to,
        sort_order=sort,
        source=selected_source,
    )
    result_page = paginate_documents(results, page=page, page_size=page_size)
    selected_tags, text_query = parse_search_query(q)
    payload = {
        "results": (
            [
                _document_payload(
                    document,
                    matching_entry_count=len(
                        document.matching_entries(
                            selected_tags,
                            text_query,
                            selected_source,
                        )
                    ) if q or selected_source else 0,
                    include_tag_entry_anchors=True,
                )
                for document in result_page.items
            ]
            if compact
            else [
                _document_payload(
                    document,
                    include_entries=bool(q or selected_source),
                )
                for document in results
            ]
        ),
        "total_results": result_page.total_results,
        "page": result_page.page,
        "page_size": result_page.page_size,
        "total_pages": result_page.total_pages,
        "has_previous": result_page.has_previous,
        "has_next": result_page.has_next,
        "document_count": len(documents),
        "tag_cloud": view.tag_cloud,
        "sources": sources,
        "selected_source": selected_source,
    }
    if compact:
        payload["tree"] = _tree_payload(shallow_tree(view.tree))
    else:
        payload["documents"] = [
            _document_payload(document) for document in documents
        ]
    return payload


@router.get("/tree")
async def hfl_api_tree(
    request: Request,
    path: str = "",
    include_secrets: bool = False,
    secret_tags: str = "",
):
    _authorize(request)
    view = corpus_view_cache.get(
        corpus_index.documents(),
        include_secrets=include_secrets,
        secret_tags=normalize_secret_tags(secret_tags),
    )
    node = find_tree_node(view.tree, path)
    if not node:
        raise HTTPException(status_code=404, detail="Corpus directory not found")
    return {"tree": _tree_payload(shallow_tree(node))}


@router.get("/matches/{relative_path:path}")
async def hfl_api_matches(
    request: Request,
    relative_path: str,
    q: str = "",
    source: str = "",
    offset: int = 0,
    limit: int = 20,
    include_secrets: bool = False,
    secret_tags: str = "",
):
    _authorize(request)
    document = corpus_index.get(relative_path)
    if not document:
        raise HTTPException(status_code=404, detail="Corpus document not found")
    selected_tags, text_query = parse_search_query(q)
    protected_tags = normalize_secret_tags(secret_tags)
    view = corpus_view_cache.get(
        corpus_index.documents(),
        include_secrets=include_secrets,
        secret_tags=protected_tags,
    )
    selected_source = normalize_source(source, view.sources)
    visible_document = document if include_secrets else filter_document(
        document, protected_tags
    )
    entries = visible_document.matching_entries(
        selected_tags,
        text_query,
        selected_source,
    )
    normalized_offset = max(0, offset)
    normalized_limit = min(max(1, limit), 20)
    return {
        "entries": [
            asdict(entry)
            for entry in entries[
                normalized_offset: normalized_offset + normalized_limit
            ]
        ],
        "total": len(entries),
        "offset": normalized_offset,
        "limit": normalized_limit,
    }


@router.get("/document/{relative_path:path}")
async def hfl_api_document(
    request: Request,
    relative_path: str,
    include_secrets: bool = False,
    secret_tags: str = "",
):
    _authorize(request)
    document = corpus_index.get(relative_path)
    if not document or document.path is None:
        raise HTTPException(status_code=404, detail="Corpus document not found")
    protected_tags = normalize_secret_tags(secret_tags)
    response_document = document
    if not include_secrets and document_has_secrets(document, protected_tags):
        visible = filter_document(document, protected_tags)
        redacted_entries = tuple(
            (
                replace(
                    entry,
                    header="",
                    moment="",
                    what_happened="",
                    tags=(),
                    source="",
                    text="",
                    secret=True,
                )
                if is_secret_entry(entry, protected_tags)
                else entry
            )
            for entry in document.entries
        )
        response_document = replace(
            visible,
            entries=redacted_entries,
            entry_count=len(redacted_entries),
        )
    root = resolve_corpus_root()
    references = []
    for raw_reference in response_document.references:
        reference = resolve_reference(
            raw_reference,
            source_document=document.path,
            corpus_root=root,
        )
        item = asdict(reference)
        if reference.kind == "download" and reference.href:
            item["token"] = reference.href.split("/")[-2]
            item["href"] = None
            path = load_download_token(
                item["token"],
                allowed_reference_roots(root),
            )
            preview = classify_preview(path) if path else None
            if preview:
                item["preview_kind"] = preview.kind
        if reference.kind in {"download", "external"} and (
            reference.href or item.get("token")
        ):
            references.append(item)
    return {
        "document": _document_payload(
            response_document,
            include_text=True,
            include_entries=True,
        ),
        "references": references,
    }


@router.post("/document/{relative_path:path}")
async def hfl_api_update_document(
    request: Request,
    relative_path: str,
    payload: UpdateDocumentRequest,
):
    _authorize(request)
    document = corpus_index.get(relative_path)
    if not document:
        raise HTTPException(status_code=404, detail="Corpus document not found")
    try:
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
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except OSError as exc:
        _log.exception("Canonical HFL document update failed")
        raise HTTPException(
            status_code=500,
            detail="The corpus document could not be saved.",
        ) from exc


@router.get("/reference/{token}")
async def hfl_api_reference(request: Request, token: str):
    _authorize(request)
    root = resolve_corpus_root()
    path = load_download_token(token, allowed_reference_roots(root))
    if not path:
        raise HTTPException(status_code=404, detail="Reference unavailable")
    return FileResponse(path, filename=path.name, media_type="application/octet-stream")


@router.get("/reference/{token}/preview")
async def hfl_api_reference_preview(request: Request, token: str):
    _authorize(request)
    path, preview = _preview_reference_path(token)
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


@router.get("/reference/{token}/media")
async def hfl_api_reference_media(request: Request, token: str):
    _authorize(request)
    path, preview = _preview_reference_path(token)
    if preview.kind not in {"image", "video"}:
        raise HTTPException(status_code=415, detail="This is not a media reference.")
    return FileResponse(
        path,
        filename=path.name,
        media_type=preview.media_type,
        content_disposition_type="inline",
        headers={
            "Accept-Ranges": "bytes",
            "Cache-Control": "private, no-store",
            "X-Content-Type-Options": "nosniff",
        },
    )


@router.get("/reference/{token}/thumbnail")
async def hfl_api_reference_thumbnail(request: Request, token: str):
    _authorize(request)
    path, preview = _preview_reference_path(token)
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
