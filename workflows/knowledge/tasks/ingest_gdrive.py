"""
workflows/knowledge/tasks/ingest_gdrive.py

Index Google Docs into the local vector store. Sheets and Slides are skipped
in v1 — their content shape (cells, slides) is qualitatively different from
narrative text and would benefit from a dedicated extractor. Binary files
(PDFs, images, etc.) are skipped too.

Pipeline:
  1. files().list with q="mimeType='application/vnd.google-apps.document'"
  2. For each Doc: export as text/plain → chunk → embed → upsert
  3. source='gdrive', chunk id = f"{file_id}:{idx}"

Default schedule: nightly 03:15. Drive's API quotas are generous (1B reads/day
per project) so this can re-ingest the whole corpus daily without strain — but
we still respect `max_files` to keep embedding cost bounded while you watch
the bill.
"""

from __future__ import annotations

from typing import Any

from core.apps.sprout.app.celery import SPROUT
from core.apps.es_logging.app.elasticsearch import log_result
from core.utilities.logging.custom_logger import create_logger

from apps.gemini.references.web.api.embed import ApiServiceGeminiEmbed
from apps.google_apps.references.web.api.drive import ApiServiceGoogleDrive
from apps.google_drive.config import CONFIG as GDRIVE_CONFIG
from apps.sqlite_vec import store

from workflows.knowledge.chunking import chunk_text

_log = create_logger("knowledge.ingest_gdrive")

_BATCH_SIZE = 50
_DOC_MIME = "application/vnd.google-apps.document"


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


def _doc_url(file_id: str) -> str:
    return f"https://docs.google.com/document/d/{file_id}/edit"


def _build_query(folder_id: str | None, modified_after: str | None) -> str:
    parts = [f"mimeType='{_DOC_MIME}'", "trashed = false"]
    if folder_id:
        parts.append(f"'{folder_id}' in parents")
    if modified_after:
        parts.append(f"modifiedTime > '{modified_after}'")
    return " and ".join(parts)


@SPROUT.task()
@log_result()
def ingest_gdrive_docs(**kwargs):
    """Sync Google Docs into the local vector store.

    Args:
        folder_id:        Restrict to one Drive folder (default: search whole Drive).
        max_files:        Cap files per run (default 200) — keep low at first
                          while you observe Gemini cost.
        modified_after:   RFC 3339 timestamp; skip Docs unchanged before it
                          (e.g. '2026-04-01T00:00:00Z'). Use for incremental ingest.
        rebuild:          If True, drop the 'gdrive' source first (default False).

    Returns:
        Summary dict — files_seen, chunks_written, skipped.
    """
    folder_id: str | None = kwargs.get("folder_id")
    max_files: int = int(kwargs.get("max_files", 200))
    modified_after: str | None = kwargs.get("modified_after")
    rebuild: bool = bool(kwargs.get("rebuild", False))

    if rebuild:
        deleted = store.delete_by_source("gdrive")
        _log.info("ingest_gdrive_docs: rebuild=True dropped %d existing chunks", deleted)

    svc = ApiServiceGoogleDrive(GDRIVE_CONFIG)

    from apps.gemini.config import CONFIG as GEMINI_CONFIG
    embedder = ApiServiceGeminiEmbed(GEMINI_CONFIG)

    query = _build_query(folder_id, modified_after)
    files = svc.list_files(query=query, page_size=min(max_files, 1000))
    files = files[:max_files]
    _log.info("ingest_gdrive_docs: discovered %d Google Doc(s) (query=%s)", len(files), query)

    files_seen = 0
    chunks_written = 0
    skipped: list[dict[str, Any]] = []

    for f in files:
        file_id = f.get("id")
        name = f.get("name") or "(untitled)"
        if not file_id:
            continue

        try:
            content_bytes = svc.export_file(file_id=file_id, mime_type="text/plain")
        except Exception as exc:
            _log.warning("ingest_gdrive_docs: %s '%s' export failed — %s", file_id, name, exc)
            skipped.append({"id": file_id, "name": name, "reason": str(exc)})
            continue

        text = (content_bytes or b"").decode("utf-8", errors="replace").strip()
        chunks = chunk_text(text)
        if not chunks:
            skipped.append({"id": file_id, "name": name, "reason": "empty"})
            continue

        url = _doc_url(file_id)
        meta_base = {
            "file_id": file_id,
            "name": name,
            "modified_time": f.get("modifiedTime"),
            "mime_type": f.get("mimeType"),
        }

        for batch_start in range(0, len(chunks), _BATCH_SIZE):
            slice_ = chunks[batch_start : batch_start + _BATCH_SIZE]
            vectors = _embed_batch(embedder, slice_)
            for offset, (chunk, vec) in enumerate(zip(slice_, vectors)):
                idx = batch_start + offset
                store.upsert(
                    chunk_id=f"{file_id}:{idx}",
                    text=chunk,
                    embedding=vec,
                    source="gdrive",
                    ref=url,
                    meta={**meta_base, "chunk_idx": idx},
                )
                chunks_written += 1

        files_seen += 1
        _log.info("ingest_gdrive_docs: %s '%s' — %d chunks", file_id, name, len(chunks))

    summary = {
        "files_seen": files_seen,
        "chunks_written": chunks_written,
        "skipped": len(skipped),
        "source": "gdrive",
        "rebuild": rebuild,
    }
    _log.info("ingest_gdrive_docs: done — %s", summary)
    return summary
