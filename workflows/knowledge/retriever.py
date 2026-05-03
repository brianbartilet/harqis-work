"""
Query-side retriever.

Embeds a question with Gemini using `RETRIEVAL_QUERY` (asymmetric — different
encoding from the `RETRIEVAL_DOCUMENT` task type used during ingestion), runs
KNN against the local sqlite-vec store, and returns the hits as-is.

This is the same shape every RAG capability in `docs/thesis/HARQIS-RAG-WORKFLOW.md`
relies on — Notion, Jira, code QA all share this retriever.
"""

from __future__ import annotations

from typing import Any, Optional

from apps.gemini.config import CONFIG as GEMINI_CONFIG
from apps.gemini.references.web.api.embed import ApiServiceGeminiEmbed
from apps.sqlite_vec import store


def embed_query(text: str) -> list[float]:
    """Embed a query as `RETRIEVAL_QUERY` — pairs with `RETRIEVAL_DOCUMENT` ingestion."""
    embedder = ApiServiceGeminiEmbed(GEMINI_CONFIG)
    resp = embedder.embed_content(text=text, task_type="RETRIEVAL_QUERY")
    data = resp.__dict__ if hasattr(resp, "__dict__") else resp
    embedding_obj = data.get("embedding") if isinstance(data, dict) else None
    if hasattr(embedding_obj, "values"):
        return list(embedding_obj.values)
    if isinstance(embedding_obj, dict):
        return list(embedding_obj.get("values", []))
    raise RuntimeError(f"Unexpected Gemini embed response shape: {data!r}")


def retrieve(
    question: str,
    k: int = 5,
    source: Optional[str] = None,
) -> list[dict[str, Any]]:
    """Embed → KNN → return top-k hits."""
    vec = embed_query(question)
    return store.search(vec, k=k, source=source)


def format_context(hits: list[dict[str, Any]]) -> str:
    """Render hits as a numbered context block for the answer prompt."""
    parts: list[str] = []
    for i, h in enumerate(hits, start=1):
        ref = h.get("ref") or h.get("id")
        parts.append(f"[{i}] (ref: {ref})\n{h['text']}")
    return "\n\n---\n\n".join(parts)
