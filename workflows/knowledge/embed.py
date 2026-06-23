"""
workflows/knowledge/embed.py

Single embedding entry point for the knowledge / RAG workflow.

Before this module existed, every ingest task carried its own copy of
``_embed_batch`` (notion / jira / github / gdrive — four identical functions)
and the retriever had its own ``embed_query``. When Google retired
``text-embedding-004`` that was *five* places to edit. This module collapses
them to one:

    embed_documents(texts)  -> list[list[float]]   # asymmetric: RETRIEVAL_DOCUMENT
    embed_query(text)       -> list[float]          # asymmetric: RETRIEVAL_QUERY

Asymmetric task types (document vs query) measurably improve recall and are the
same convention the old code relied on — kept verbatim.

Provider / model are env-driven so a future swap (depleted credits, a better
model) is zero code change:

    HARQIS_KNOWLEDGE_EMBED_PROVIDER   default "gemini"
    HARQIS_KNOWLEDGE_EMBED_MODEL      default "models/gemini-embedding-001"
    HARQIS_KNOWLEDGE_EMBED_BATCH      default "50"  (texts per API call)

Only the Gemini provider is implemented today (the platform default). The
dispatch table leaves a clean seam for ``openai`` / ``local`` without touching
any caller.
"""

from __future__ import annotations

import os
from typing import Any, Callable

from core.utilities.logging.custom_logger import create_logger

_log = create_logger("knowledge.embed")

_DEFAULT_MODEL = "models/gemini-embedding-001"
_DEFAULT_BATCH = 50


def _model() -> str:
    return os.environ.get("HARQIS_KNOWLEDGE_EMBED_MODEL", "").strip() or _DEFAULT_MODEL


def _batch_size() -> int:
    raw = os.environ.get("HARQIS_KNOWLEDGE_EMBED_BATCH", "").strip()
    try:
        return max(1, int(raw)) if raw else _DEFAULT_BATCH
    except ValueError:
        return _DEFAULT_BATCH


def _provider() -> str:
    return os.environ.get("HARQIS_KNOWLEDGE_EMBED_PROVIDER", "").strip().lower() or "gemini"


# --------------------------------------------------------------------------- #
# Gemini provider
# --------------------------------------------------------------------------- #

def _gemini_embedder():
    """Late import — keeps the Gemini app off the hot import path and lets the
    module import cleanly in environments where it isn't configured."""
    from apps.gemini.config import CONFIG as GEMINI_CONFIG
    from apps.gemini.references.web.api.embed import ApiServiceGeminiEmbed
    return ApiServiceGeminiEmbed(GEMINI_CONFIG)


def _values(item: Any) -> list[float]:
    """Pull the float vector out of one Gemini embedding item.

    Gemini returns either dicts (``{"values": [...]}``) or attribute objects
    (``item.values``) depending on the deserialiser path — handle both.
    """
    values = item.get("values") if isinstance(item, dict) else getattr(item, "values", None)
    if values is None:
        raise RuntimeError(f"Gemini embedding item has no values: {item!r}")
    return list(values)


def _gemini_documents(texts: list[str]) -> list[list[float]]:
    embedder = _gemini_embedder()
    model = _model()
    out: list[list[float]] = []
    for start in range(0, len(texts), _batch_size()):
        slice_ = texts[start : start + _batch_size()]
        resp = embedder.batch_embed_contents(
            texts=slice_, model=model, task_type="RETRIEVAL_DOCUMENT"
        )
        data = resp.__dict__ if hasattr(resp, "__dict__") else resp
        embeddings = data.get("embeddings", []) if isinstance(data, dict) else []
        batch = [_values(e) for e in embeddings]
        if len(batch) != len(slice_):
            raise RuntimeError(
                f"Gemini batch returned {len(batch)} embeddings for {len(slice_)} texts "
                f"(model={model}). Response head: {str(data)[:200]!r}"
            )
        out.extend(batch)
    return out


def _gemini_query(text: str) -> list[float]:
    embedder = _gemini_embedder()
    resp = embedder.embed_content(text=text, model=_model(), task_type="RETRIEVAL_QUERY")
    data = resp.__dict__ if hasattr(resp, "__dict__") else resp
    embedding_obj = data.get("embedding") if isinstance(data, dict) else None
    if embedding_obj is None:
        raise RuntimeError(f"Unexpected Gemini embed response shape: {data!r}")
    return _values(embedding_obj)


# --------------------------------------------------------------------------- #
# Dispatch
# --------------------------------------------------------------------------- #

_DOC_PROVIDERS: dict[str, Callable[[list[str]], list[list[float]]]] = {
    "gemini": _gemini_documents,
}
_QUERY_PROVIDERS: dict[str, Callable[[str], list[float]]] = {
    "gemini": _gemini_query,
}


def embed_documents(texts: list[str]) -> list[list[float]]:
    """Embed a list of documents (RETRIEVAL_DOCUMENT). Batches internally.

    Returns one vector per input text, in order. Raises if the provider
    returns a different count than requested (so a silent partial never
    corrupts the index).
    """
    if not texts:
        return []
    provider = _provider()
    fn = _DOC_PROVIDERS.get(provider)
    if fn is None:
        raise RuntimeError(
            f"Unknown embed provider {provider!r} — set HARQIS_KNOWLEDGE_EMBED_PROVIDER "
            f"to one of: {', '.join(sorted(_DOC_PROVIDERS))}"
        )
    return fn(texts)


def embed_query(text: str) -> list[float]:
    """Embed a single query (RETRIEVAL_QUERY) — pairs with embed_documents()."""
    provider = _provider()
    fn = _QUERY_PROVIDERS.get(provider)
    if fn is None:
        raise RuntimeError(
            f"Unknown embed provider {provider!r} — set HARQIS_KNOWLEDGE_EMBED_PROVIDER "
            f"to one of: {', '.join(sorted(_QUERY_PROVIDERS))}"
        )
    return fn(text)
