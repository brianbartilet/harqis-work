"""
workflows/knowledge/tasks/ingest_confluence.py

Index Confluence pages into the local vector store — the Phase-1 source the
knowledge radar was missing. In a large org (think a bank with dozens of
service teams) Confluence is where the integration docs, runbooks, and design
decisions live; this makes all of it semantically retrievable next to Jira,
GitHub, and your HFL timeline.

Pipeline (per run):
  1. Enumerate pages with CQL (`space in (...) and type = page order by
     lastmodified desc`), version + labels expanded — cheap, no bodies.
  2. INCREMENTAL: compare each page's live `version.number` against the version
     already stored. Unchanged → skip (no body fetch, no embedding).
  3. For changed/new pages: fetch body.storage, flatten the XHTML, compose
     title + breadcrumb + labels + body, chunk, embed (RETRIEVAL_DOCUMENT).
  4. Upsert keyed f"{page_id}:{chunk_idx}", source='confluence'.

Idempotent: re-running re-ingests only what changed. `rebuild=True` drops the
source first for a clean reindex.

Default schedule: nightly 03:30 (staggered after the other ingestors). The beat
entry ships disabled — enable it in tasks_config.py once Confluence creds are
set in .env/apps.env and Gemini embedding credits are funded.
"""

from __future__ import annotations

from typing import Any

from core.apps.sprout.app.celery import SPROUT
from core.apps.es_logging.app.elasticsearch import log_result
from core.utilities.logging.custom_logger import create_logger

from apps.apps_config import CONFIG_MANAGER
from apps.confluence.references.web.api.content import ApiServiceConfluenceContent
from apps.sqlite_vec import store

from workflows.knowledge.chunking import chunk_text, strip_confluence_storage
from workflows.knowledge.embed import embed_documents

_log = create_logger("knowledge.ingest_confluence")

_BATCH_SIZE = 50
_SOURCE = "confluence"


def _labels(page: dict[str, Any]) -> list[str]:
    results = (((page.get("metadata") or {}).get("labels") or {}).get("results")) or []
    return [r.get("name", "") for r in results if r.get("name")]


def _version(page: dict[str, Any]) -> int:
    try:
        return int(((page.get("version") or {}).get("number")) or 0)
    except (TypeError, ValueError):
        return 0


def _breadcrumb(page: dict[str, Any]) -> str:
    """Ancestor titles → a 'A > B > C' breadcrumb (needs expand=ancestors)."""
    titles = [a.get("title", "") for a in (page.get("ancestors") or []) if a.get("title")]
    return " > ".join(titles)


def _page_url(page: dict[str, Any], base: str) -> str:
    webui = ((page.get("_links") or {}).get("webui")) or ""
    if webui:
        return f"{base.rstrip('/')}{webui}" if base else webui
    pid = page.get("id", "")
    return f"{base.rstrip('/')}/pages/viewpage.action?pageId={pid}" if base else pid


def _compose_text(page: dict[str, Any], body_text: str) -> str:
    title = page.get("title") or ""
    space = ((page.get("space") or {}).get("key")) or ""
    crumb = _breadcrumb(page)
    labels = _labels(page)
    head = title
    if space:
        head = f"[{space}] {head}"
    parts = [head]
    if crumb:
        parts.append(f"Location: {crumb}")
    if labels:
        parts.append("Labels: " + ", ".join(labels))
    if body_text:
        parts.append(body_text)
    return "\n\n".join(p for p in parts if p)


@SPROUT.task()
@log_result()
def ingest_confluence_pages(**kwargs):
    """Sync Confluence pages into the local vector store (incremental).

    Args:
        cfg_id__confluence: Config key for Confluence (default 'CONFLUENCE').
        space_keys:         Spaces to ingest, e.g. ['ENG', 'OPS']. Empty → all
                            visible pages (CQL falls back to type=page only).
        cql_extra:          Extra CQL appended with AND, e.g.
                            "lastmodified >= '2026-06-01'" for a tighter window.
        max_pages:          Cap pages enumerated per run (default 500).
        rebuild:            If True, drop the 'confluence' source first.
        force:              If True, ignore stored versions and re-ingest every
                            page (default False — incremental skip is on).

    Returns:
        Summary dict — pages_seen, pages_ingested, pages_skipped, chunks_written.
    """
    cfg_id__confluence: str = kwargs.get("cfg_id__confluence", "CONFLUENCE")
    space_keys: list[str] = list(kwargs.get("space_keys", []) or [])
    cql_extra: str = kwargs.get("cql_extra", "") or ""
    max_pages: int = int(kwargs.get("max_pages", 500))
    rebuild: bool = bool(kwargs.get("rebuild", False))
    force: bool = bool(kwargs.get("force", False))

    if rebuild:
        deleted = store.delete_by_source(_SOURCE)
        _log.info("ingest_confluence_pages: rebuild=True dropped %d existing chunks", deleted)

    svc = ApiServiceConfluenceContent(CONFIG_MANAGER.get(cfg_id__confluence))

    # Build {page_id: stored_version} once for incremental skipping.
    stored_versions: dict[str, int] = {}
    if not rebuild:
        for row in store.get_meta_by_source(_SOURCE):
            meta = row.get("meta") or {}
            pid = meta.get("page_id")
            if pid is not None:
                stored_versions[str(pid)] = max(
                    stored_versions.get(str(pid), 0), int(meta.get("version") or 0)
                )

    # Compose CQL.
    clauses = ["type = page"]
    if space_keys:
        clauses.append("space in (" + ",".join(space_keys) + ")")
    if cql_extra:
        clauses.append(cql_extra)
    cql = " and ".join(clauses) + " order by lastmodified desc"

    pages_seen = 0
    pages_ingested = 0
    pages_skipped = 0
    chunks_written = 0
    start = 0

    while pages_seen < max_pages:
        page_size = min(50, max_pages - pages_seen)
        resp = svc.search_cql(cql=cql, limit=page_size, start=start)
        if not isinstance(resp, dict):
            _log.warning("ingest_confluence_pages: unexpected search response: %r", resp)
            break
        results = resp.get("results", []) or []
        if not results:
            break
        base = ((resp.get("_links") or {}).get("base")) or ""

        for summary in results:
            pages_seen += 1
            page_id = summary.get("id")
            if not page_id:
                continue
            live_version = _version(summary)
            if not force and stored_versions.get(str(page_id), -1) == live_version and live_version:
                pages_skipped += 1
                continue

            # Changed/new → fetch the full body (expensive call, only now).
            try:
                page = svc.get_page(page_id)
            except Exception as exc:  # noqa: BLE001
                _log.warning("ingest_confluence_pages: get_page %s failed — %s", page_id, exc)
                continue
            if not isinstance(page, dict):
                continue

            body_html = (((page.get("body") or {}).get("storage") or {}).get("value")) or ""
            body_text = strip_confluence_storage(body_html)
            text = _compose_text(page, body_text)
            chunks = chunk_text(text)
            if not chunks:
                continue

            url = _page_url(page, base)
            meta_base = {
                "page_id": str(page_id),
                "title": page.get("title", ""),
                "space": ((page.get("space") or {}).get("key")) or "",
                "version": _version(page),
                "labels": _labels(page),
                "breadcrumb": _breadcrumb(page),
            }

            for batch_start in range(0, len(chunks), _BATCH_SIZE):
                slice_ = chunks[batch_start : batch_start + _BATCH_SIZE]
                vectors = embed_documents(slice_)
                for offset, (chunk, vec) in enumerate(zip(slice_, vectors)):
                    idx = batch_start + offset
                    store.upsert(
                        chunk_id=f"{page_id}:{idx}",
                        text=chunk,
                        embedding=vec,
                        source=_SOURCE,
                        ref=url,
                        meta={**meta_base, "chunk_idx": idx},
                    )
                    chunks_written += 1

            pages_ingested += 1
            _log.info("ingest_confluence_pages: %s '%s' v%d — %d chunks",
                      page_id, meta_base["title"][:60], meta_base["version"], len(chunks))

        start += page_size
        if start >= int(resp.get("totalSize", resp.get("size", 0)) or 0):
            break

    summary = {
        "pages_seen": pages_seen,
        "pages_ingested": pages_ingested,
        "pages_skipped": pages_skipped,
        "chunks_written": chunks_written,
        "source": _SOURCE,
        "rebuild": rebuild,
        "cql": cql,
    }
    _log.info("ingest_confluence_pages: done — %s", summary)
    return summary
