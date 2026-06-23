"""
Query-side retriever.

Embeds a question with `RETRIEVAL_QUERY` (asymmetric — different encoding from
the `RETRIEVAL_DOCUMENT` task type used during ingestion), runs KNN against the
local sqlite-vec store, and returns the hits as-is.

This is the same shape every RAG capability in `docs/thesis/RAG-WORKFLOW.md`
relies on — Notion, Jira, Confluence, code QA all share this retriever. The
embedding provider/model lives in `workflows/knowledge/embed.py` (one place to
swap), not here.
"""

from __future__ import annotations

from typing import Any, Optional

from apps.sqlite_vec import store

from workflows.knowledge.embed import embed_query


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
