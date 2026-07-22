"""Routes for browsing and searching the HFL corpus."""

import re
from urllib.parse import quote, urlencode

from fastapi import APIRouter, Request
from fastapi.responses import FileResponse, HTMLResponse, Response
from markupsafe import Markup

from config import get_settings
from modules.hfl_corpus.corpus import (
    CorpusPage,
    build_tree,
    common_tags,
    corpus_index,
    find_tree_node,
    format_hfl_markdown,
    paginate_documents,
    parse_search_query,
    resolve_corpus_root,
    search_documents,
    shallow_tree,
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
    page: int = 1,
    page_size: int = 20,
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
    if page != 1:
        params["page"] = page
    if page_size != 20 or page != 1:
        params["page_size"] = page_size
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
                "page": str(page),
                "page_size": str(page_size),
            })
            documents = remote["documents"]
            tree = remote["tree"]
            results = remote["results"]
            total_results = remote["total_results"]
            document_count = remote["document_count"]
            tag_cloud = remote["tag_cloud"]
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
            result_page = paginate_documents((), page=page, page_size=page_size)
            remote_error = str(exc)
    else:
        documents = corpus_index.documents()
        tree = shallow_tree(build_tree(documents))
        all_results = search_documents(
            documents,
            query=q,
            date_field=date_field,
            date_from=date_from,
            date_to=date_to,
            sort_order=sort,
        )
        result_page = paginate_documents(all_results, page=page, page_size=page_size)
        results = result_page.items
        total_results = result_page.total_results
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
        page_size=result_page.page_size,
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
                page_size=result_page.page_size,
            ),
        })
    page_url_values = {
        "query": q,
        "date_field": date_field,
        "date_from": date_from,
        "date_to": date_to,
        "sort": sort,
        "page_size": result_page.page_size,
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
            sort_order=sort,
            sort_toggle_url=sort_toggle_url,
            result_page=result_page,
            previous_page_url=previous_page_url,
            next_page_url=next_page_url,
            tag_cloud=tag_options,
            remote_error=remote_error,
        ),
    )


@router.get("/tree", response_class=HTMLResponse, name="hfl_tree")
async def hfl_tree(request: Request, path: str = ""):
    user, redirect = require_user(request)
    if redirect:
        return redirect
    if _uses_remote_corpus():
        try:
            branch = RemoteCorpusClient.from_settings().tree(path)
        except RemoteCorpusError as exc:
            return HTMLResponse(str(exc), status_code=502)
    else:
        tree = build_tree(corpus_index.documents())
        node = find_tree_node(tree, path)
        if not node:
            return HTMLResponse("Corpus directory not found", status_code=404)
        branch = shallow_tree(node)
    return templates.TemplateResponse(
        request,
        "modules/hfl_corpus/partials/tree.html",
        {"tree": branch},
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
    offset: int = 0,
    limit: int = 20,
):
    user, redirect = require_user(request)
    if redirect:
        return redirect
    if _uses_remote_corpus():
        try:
            match_page = RemoteCorpusClient.from_settings().matches(
                relative_path,
                query=q,
                offset=offset,
                limit=limit,
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
        matching_entries = document.matching_entries(selected_tags, text_query)
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
            "selected_tag": selected_tags[0] if len(selected_tags) == 1 else "",
        },
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
