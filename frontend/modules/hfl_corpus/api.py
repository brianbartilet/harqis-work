"""Authenticated read and manual-entry API for the canonical HFL corpus host."""

from __future__ import annotations

import hmac
from dataclasses import asdict

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse

from config import get_settings
from modules.hfl_corpus.corpus import (
    CorpusDocument,
    build_tree,
    common_tags,
    corpus_index,
    find_tree_node,
    paginate_documents,
    parse_search_query,
    resolve_corpus_root,
    search_documents,
    shallow_tree,
)
from modules.hfl_corpus.entry_create import CreateEntryRequest, persist_manual_entry
from services.safe_paths import (
    allowed_reference_roots,
    load_download_token,
    resolve_reference,
)


router = APIRouter(prefix="/api/hfl", tags=["hfl-corpus-api"])


def _authorize(request: Request) -> None:
    expected = get_settings().hfl_corpus_api_token.strip()
    if not expected:
        raise HTTPException(status_code=503, detail="HFL corpus API token is not configured")
    scheme, _, supplied = request.headers.get("Authorization", "").partition(" ")
    if scheme.casefold() != "bearer" or not hmac.compare_digest(supplied, expected):
        raise HTTPException(status_code=401, detail="Invalid HFL corpus API token")


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
        payload["tag_entry_anchors"] = [
            [tag, matches[0].anchor]
            for tag in document.tags
            if (matches := document.matching_entries(tag))
        ]
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
):
    _authorize(request)
    if date_field not in {"created", "updated"}:
        date_field = "created"
    if sort not in {"asc", "desc"}:
        sort = "desc"
    documents = corpus_index.documents()
    results = search_documents(
        documents,
        query=q,
        date_field=date_field,
        date_from=date_from,
        date_to=date_to,
        sort_order=sort,
    )
    result_page = paginate_documents(results, page=page, page_size=page_size)
    selected_tags, text_query = parse_search_query(q)
    payload = {
        "results": (
            [
                _document_payload(
                    document,
                    matching_entry_count=len(
                        document.matching_entries(selected_tags, text_query)
                    ) if q else 0,
                    include_tag_entry_anchors=True,
                )
                for document in result_page.items
            ]
            if compact
            else [
                _document_payload(document, include_entries=bool(q))
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
        "tag_cloud": common_tags(documents),
    }
    if compact:
        payload["tree"] = _tree_payload(shallow_tree(build_tree(documents)))
    else:
        payload["documents"] = [
            _document_payload(document) for document in documents
        ]
    return payload


@router.get("/tree")
async def hfl_api_tree(request: Request, path: str = ""):
    _authorize(request)
    tree = build_tree(corpus_index.documents())
    node = find_tree_node(tree, path)
    if not node:
        raise HTTPException(status_code=404, detail="Corpus directory not found")
    return {"tree": _tree_payload(shallow_tree(node))}


@router.get("/matches/{relative_path:path}")
async def hfl_api_matches(
    request: Request,
    relative_path: str,
    q: str = "",
    offset: int = 0,
    limit: int = 20,
):
    _authorize(request)
    document = corpus_index.get(relative_path)
    if not document:
        raise HTTPException(status_code=404, detail="Corpus document not found")
    selected_tags, text_query = parse_search_query(q)
    entries = document.matching_entries(selected_tags, text_query)
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
async def hfl_api_document(request: Request, relative_path: str):
    _authorize(request)
    document = corpus_index.get(relative_path)
    if not document or document.path is None:
        raise HTTPException(status_code=404, detail="Corpus document not found")
    root = resolve_corpus_root()
    references = []
    for raw_reference in document.references:
        reference = resolve_reference(
            raw_reference,
            source_document=document.path,
            corpus_root=root,
        )
        item = asdict(reference)
        if reference.kind == "download" and reference.href:
            item["token"] = reference.href.split("/")[-2]
            item["href"] = None
        references.append(item)
    return {
        "document": _document_payload(
            document,
            include_text=True,
            include_entries=True,
        ),
        "references": references,
    }


@router.get("/reference/{token}")
async def hfl_api_reference(request: Request, token: str):
    _authorize(request)
    root = resolve_corpus_root()
    path = load_download_token(token, allowed_reference_roots(root))
    if not path:
        raise HTTPException(status_code=404, detail="Reference unavailable")
    return FileResponse(path, filename=path.name, media_type="application/octet-stream")
