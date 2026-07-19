"""Routes for browsing and searching the HFL corpus."""

from fastapi import APIRouter, Request
from fastapi.responses import FileResponse, HTMLResponse

from modules.hfl_corpus.corpus import (
    build_tree,
    corpus_index,
    resolve_corpus_root,
    search_documents,
)
from services.markdown import render_markdown
from services.safe_paths import (
    allowed_reference_roots,
    load_download_token,
    resolve_reference,
)
from web import page_context, require_user, templates


router = APIRouter(prefix="/hfl-corpus")


@router.get("", response_class=HTMLResponse)
async def hfl_corpus_page(
    request: Request,
    q: str = "",
    created_from: str = "",
    created_to: str = "",
    updated_from: str = "",
    updated_to: str = "",
):
    user, redirect = require_user(request)
    if redirect:
        return redirect
    documents = corpus_index.documents()
    results = search_documents(
        documents,
        query=q,
        created_from=created_from,
        created_to=created_to,
        updated_from=updated_from,
        updated_to=updated_to,
    )
    return templates.TemplateResponse(
        request,
        "modules/hfl_corpus/index.html",
        page_context(
            request,
            user,
            "hfl_corpus",
            tree=build_tree(documents),
            results=results[:200],
            total_results=len(results),
            document_count=len(documents),
            query=q,
            created_from=created_from,
            created_to=created_to,
            updated_from=updated_from,
            updated_to=updated_to,
        ),
    )


@router.get("/document/{relative_path:path}", response_class=HTMLResponse, name="hfl_document")
async def hfl_document(request: Request, relative_path: str):
    user, redirect = require_user(request)
    if redirect:
        return redirect
    document = corpus_index.get(relative_path)
    if not document:
        return HTMLResponse("Corpus document not found", status_code=404)
    root = resolve_corpus_root()
    references = [
        resolve_reference(reference, source_document=document.path, corpus_root=root)
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
            rendered=render_markdown(document.text),
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
