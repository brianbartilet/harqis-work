"""Routes for browsing and searching the HFL corpus."""

import re
from urllib.parse import quote, urlencode

from fastapi import APIRouter, Request
from fastapi.responses import FileResponse, HTMLResponse, Response
from markupsafe import Markup

from config import get_settings
from modules.hfl_corpus.corpus import (
    build_tree,
    common_tags,
    corpus_index,
    format_hfl_markdown,
    parse_search_query,
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
_H2 = re.compile(r"<h2(?:\s+[^>]*)?>")


def _anchor_rendered_entries(rendered: Markup, document) -> Markup:
    anchors = iter(entry.anchor for entry in document.entries)

    def replace(match: re.Match) -> str:
        anchor = next(anchors, "")
        return f'<h2 id="{anchor}" class="scroll-mt-40">' if anchor else match.group(0)

    return Markup(_H2.sub(replace, str(rendered)))


def _uses_remote_corpus() -> bool:
    return bool(get_settings().hfl_corpus_api_url.strip())


def _index_url(
    *,
    query: str,
    date_field: str,
    date_from: str,
    date_to: str,
    sort: str,
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
    if sort != "desc":
        params["sort"] = sort
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
    remote_error = ""
    if _uses_remote_corpus():
        try:
            remote = RemoteCorpusClient.from_settings().index(params={
                "q": q,
                "date_field": date_field,
                "date_from": date_from,
                "date_to": date_to,
                "sort": sort,
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
            sort_order=sort,
        )
        total_results = len(results)
        document_count = len(documents)
        tag_cloud = common_tags(documents)
    selected_tags, text_query = parse_search_query(q)
    reverse_sort = "asc" if sort == "desc" else "desc"
    sort_toggle_url = _index_url(
        query=q,
        date_field=date_field,
        date_from=date_from,
        date_to=date_to,
        sort=reverse_sort,
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
                sort=sort,
            ),
        })
    return templates.TemplateResponse(
        request,
        "modules/hfl_corpus/index.html",
        page_context(
            request,
            user,
            "hfl_corpus",
            tree=build_tree(documents),
            results=results if (q or date_from or date_to) else results[:10],
            total_results=total_results,
            document_count=document_count,
            query=q,
            selected_tags=selected_tags,
            selected_tag=selected_tags[0] if len(selected_tags) == 1 else "",
            text_query=text_query,
            date_field=date_field,
            date_from=date_from,
            date_to=date_to,
            sort_order=sort,
            sort_toggle_url=sort_toggle_url,
            tag_cloud=tag_options,
            remote_error=remote_error,
        ),
    )


@router.get("/document/{relative_path:path}", response_class=HTMLResponse, name="hfl_document")
async def hfl_document(request: Request, relative_path: str, tag: str = ""):
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
    rendered = render_markdown(format_hfl_markdown(document.text))
    return templates.TemplateResponse(
        request,
        "modules/hfl_corpus/document.html",
        page_context(
            request,
            user,
            "hfl_corpus",
            document=document,
            rendered=_anchor_rendered_entries(rendered, document),
            references=references,
            selected_tag=tag.casefold(),
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
