"""
workflows/knowledge/tasks/ingest_notion.py

Pull every Notion page accessible to the configured integration, chunk each
page, embed the chunks with Gemini (`RETRIEVAL_DOCUMENT`), and upsert into the
local sqlite-vec store.

Pipeline:
  1. Notion search → list of pages
  2. For each page: fetch children blocks → flatten to plain text → chunk
  3. Batch-embed chunks with Gemini
  4. Upsert into apps/sqlite_vec keyed by f"{page_id}:{chunk_idx}"

Idempotent: re-running replaces existing chunks for any page seen again
(same chunk id → upsert overwrites). To do a clean rebuild, call
`apps.sqlite_vec.store.delete_by_source('notion')` first.

Default schedule: nightly (set in workflows/knowledge/tasks_config.py).
"""

from __future__ import annotations

from typing import Any

from core.apps.sprout.app.celery import SPROUT
from core.apps.es_logging.app.elasticsearch import log_result
from core.utilities.logging.custom_logger import create_logger

from apps.apps_config import CONFIG_MANAGER
from apps.gemini.references.web.api.embed import ApiServiceGeminiEmbed
from apps.notion.references.web.api.search import ApiServiceNotionSearch
from apps.notion.references.web.api.blocks import ApiServiceNotionBlocks
from apps.sqlite_vec import store

from workflows.knowledge.chunking import (
    chunk_text,
    extract_notion_block_text,
    iter_notion_blocks,
)

_log = create_logger("knowledge.ingest_notion")

_BATCH_SIZE = 50  # Gemini batchEmbedContents limit is 100; 50 leaves headroom


def _page_title(page: dict[str, Any]) -> str:
    """Best-effort title extraction across page property shapes."""
    props = page.get("properties") or {}
    for prop in props.values():
        if not isinstance(prop, dict) or prop.get("type") != "title":
            continue
        title_rich = prop.get("title") or []
        if title_rich:
            return "".join(t.get("plain_text", "") for t in title_rich)
    return page.get("id", "(untitled)")


def _page_to_text(page_id: str, blocks_service: ApiServiceNotionBlocks) -> str:
    parts: list[str] = []
    for block in iter_notion_blocks(page_id, blocks_service):
        text = extract_notion_block_text(block)
        if text:
            parts.append(text)
    return "\n\n".join(parts)


def _embed_batch(embedder: ApiServiceGeminiEmbed, texts: list[str]) -> list[list[float]]:
    resp = embedder.batch_embed_contents(texts=texts, task_type="RETRIEVAL_DOCUMENT")
    data = resp.__dict__ if hasattr(resp, "__dict__") else resp
    embeddings = data.get("embeddings", []) if isinstance(data, dict) else []
    out: list[list[float]] = []
    for e in embeddings:
        values = e.get("values") if isinstance(e, dict) else getattr(e, "values", None)
        if values is None:
            raise RuntimeError(f"Gemini batch returned an item with no values: {e!r}")
        out.append(list(values))
    if len(out) != len(texts):
        raise RuntimeError(f"Gemini batch returned {len(out)} embeddings for {len(texts)} texts")
    return out


@SPROUT.task()
@log_result()
def ingest_notion_pages(**kwargs):
    """Sync the user's Notion workspace into the local vector store.

    Args:
        cfg_id__notion:    Config key for Notion (default 'NOTION').
        max_pages:         Cap pages per run for incremental ingest (default 200).
        rebuild:           If True, drop the 'notion' source first (default False).

    Returns:
        Summary dict — pages_seen, chunks_written.
    """
    cfg_id__notion: str = kwargs.get("cfg_id__notion", "NOTION")
    max_pages: int = int(kwargs.get("max_pages", 200))
    rebuild: bool = bool(kwargs.get("rebuild", False))

    if rebuild:
        deleted = store.delete_by_source("notion")
        _log.info("ingest_notion_pages: rebuild=True dropped %d existing chunks", deleted)

    notion_cfg = CONFIG_MANAGER.get(cfg_id__notion)
    search = ApiServiceNotionSearch(notion_cfg)
    blocks = ApiServiceNotionBlocks(notion_cfg)

    # Use Gemini's free-tier-friendly embedder. Lazy-init to surface config
    # errors as a clear failure during the task rather than at import time.
    from apps.gemini.config import CONFIG as GEMINI_CONFIG
    embedder = ApiServiceGeminiEmbed(GEMINI_CONFIG)

    pages_seen = 0
    chunks_written = 0

    cursor: str | None = None
    while pages_seen < max_pages:
        resp = search.search(filter_object="page", page_size=100, start_cursor=cursor)
        if not isinstance(resp, dict):
            _log.warning("ingest_notion_pages: unexpected search response: %r", resp)
            break

        for page in resp.get("results", []):
            if pages_seen >= max_pages:
                break
            page_id: str = page.get("id", "")
            if not page_id:
                continue
            url: str = page.get("url") or ""
            title = _page_title(page)

            text = _page_to_text(page_id, blocks)
            chunks = chunk_text(text)
            if not chunks:
                _log.debug("ingest_notion_pages: page %s (%s) — no text", page_id, title)
                pages_seen += 1
                continue

            for batch_start in range(0, len(chunks), _BATCH_SIZE):
                batch = chunks[batch_start : batch_start + _BATCH_SIZE]
                vectors = _embed_batch(embedder, batch)
                for offset, (chunk, vec) in enumerate(zip(batch, vectors)):
                    idx = batch_start + offset
                    store.upsert(
                        chunk_id=f"{page_id}:{idx}",
                        text=chunk,
                        embedding=vec,
                        source="notion",
                        ref=url,
                        meta={"page_id": page_id, "title": title, "chunk_idx": idx},
                    )
                    chunks_written += 1

            pages_seen += 1
            _log.info(
                "ingest_notion_pages: page %s '%s' — %d chunks",
                page_id, title, len(chunks),
            )

        if not resp.get("has_more"):
            break
        cursor = resp.get("next_cursor")
        if not cursor:
            break

    summary = {
        "pages_seen": pages_seen,
        "chunks_written": chunks_written,
        "source": "notion",
        "rebuild": rebuild,
    }
    _log.info("ingest_notion_pages: done — %s", summary)
    return summary
