"""Routes for browsing and searching the HFL corpus."""

from urllib.parse import quote

from fastapi import APIRouter, Request
from fastapi.responses import FileResponse, HTMLResponse, Response

from config import get_settings
from modules.hfl_corpus.corpus import (
    build_tree,
    common_tags,
    corpus_index,
    format_hfl_markdown,
    resolve_corpus_root,
    search_documents,
)
from services.markdown import render_markdown
from modules.hfl_corpus.remote import RemoteCorpusClient, RemoteCorpusError
from services.safe_paths import (
    allowed_reference_roots,
    load_download_token,
    resolve_reference,
)
from web import page_context, require_user, templates


router = APIRouter(prefix="/hfl-corpus")


def _uses_remote_corpus() -> bool:
    return bool(get_settings().hfl_corpus_api_url.strip())


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
):
    user, redirect = require_user(request)
    if redirect:
        return redirect
    if date_field not in {"created", "updated"}:
        date_field = "created"
    # Preserve old bookmarked URLs while presenting only the simplified UI.
    if not date_from and not date_to:
        if updated_from or updated_to:
            date_field, date_from, date_to = "updated", updated_from, updated_to
        elif created_from or created_to:
            date_field, date_from, date_to = "created", created_from, created_to
    remote_error = ""
    if _uses_remote_corpus():
        try:
            remote = RemoteCorpusClient.from_settings().index(params={
                "q": q,
                "date_field": date_field,
                "date_from": date_from,
                "date_to": date_to,
            })
            documents = remote["documents"]
            results = remote["results"]
            total_results = remote["total_results"]
            document_count = remote["document_count"]
            tag_cloud = remote["tag_cloud"]
        except RemoteCorpusError as exc:
            documents = ()
            results = ()
            total_results = 0
            document_count = 0
            tag_cloud = []
            remote_error = str(exc)
    else:
        documents = corpus_index.documents()
        results = search_documents(
            documents,
            query=q,
            date_field=date_field,
            date_from=date_from,
            date_to=date_to,
        )
        total_results = len(results)
        document_count = len(documents)
        tag_cloud = common_tags(documents)
    return templates.TemplateResponse(
        request,
        "modules/hfl_corpus/index.html",
        page_context(
            request,
            user,
            "hfl_corpus",
            tree=build_tree(documents),
            results=results[:200],
            total_results=total_results,
            document_count=document_count,
            query=q,
            date_field=date_field,
            date_from=date_from,
            date_to=date_to,
            tag_cloud=tag_cloud,
            remote_error=remote_error,
        ),
    )


@router.get("/document/{relative_path:path}", response_class=HTMLResponse, name="hfl_document")
async def hfl_document(request: Request, relative_path: str):
    user, redirect = require_user(request)
    if redirect:
        return redirect
    if _uses_remote_corpus():
        try:
            document, references = RemoteCorpusClient.from_settings().document(relative_path)
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
    return templates.TemplateResponse(
        request,
        "modules/hfl_corpus/document.html",
        page_context(
            request,
            user,
            "hfl_corpus",
            document=document,
            rendered=render_markdown(format_hfl_markdown(document.text)),
            references=references,
        ),
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
