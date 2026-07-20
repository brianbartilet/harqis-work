"""Authenticated read-only API for the canonical HFL corpus host."""

from __future__ import annotations

import hmac
from dataclasses import asdict

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse

from config import get_settings
from modules.hfl_corpus.corpus import (
    CorpusDocument,
    common_tags,
    corpus_index,
    resolve_corpus_root,
    search_documents,
)
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


def _document_payload(document: CorpusDocument, *, include_text: bool = False) -> dict:
    payload = {
        "relative_path": document.relative_path,
        "name": document.name,
        "created_at": document.created_at.isoformat(),
        "updated_at": document.updated_at.isoformat(),
        "tags": list(document.tags),
        "tag_counts": [list(item) for item in document.tag_counts],
        "entry_count": document.entry_count,
        "entries": [asdict(entry) for entry in document.entries],
        "excerpt": document.excerpt,
    }
    if include_text:
        payload["text"] = document.text
    return payload


@router.get("/documents")
async def hfl_api_documents(
    request: Request,
    q: str = "",
    date_field: str = "created",
    date_from: str = "",
    date_to: str = "",
):
    _authorize(request)
    if date_field not in {"created", "updated"}:
        date_field = "created"
    documents = corpus_index.documents()
    results = search_documents(
        documents,
        query=q,
        date_field=date_field,
        date_from=date_from,
        date_to=date_to,
    )
    return {
        "documents": [_document_payload(document) for document in documents],
        "results": [_document_payload(document) for document in results],
        "total_results": len(results),
        "document_count": len(documents),
        "tag_cloud": common_tags(documents),
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
        "document": _document_payload(document, include_text=True),
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
