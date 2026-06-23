"""
workflows/knowledge/tasks/topic_scan.py

Run a watchlist against the indexed corpus and return "hit cards" — the
proactive "here's what you should know" surface. Phase-1 building block for the
daily Knowledge Radar digest (Phase 2 wires these cards to Telegram/email).

A card explains WHY it matched: the semantic similarity, which watchlist
keywords appear in the snippet, and which tracked services/entities it mentions.
That keeps the radar auditable instead of "trust me, it's relevant."
"""

from __future__ import annotations

from typing import Any

from core.apps.sprout.app.celery import SPROUT
from core.apps.es_logging.app.elasticsearch import log_result
from core.utilities.logging.custom_logger import create_logger

from workflows.knowledge.entities import extract_entities
from workflows.knowledge.retriever import retrieve
from workflows.knowledge.watchlist import get_watchlist, load_watchlists

_log = create_logger("knowledge.topic_scan")


def _similarity(distance: float) -> float:
    sim = 1.0 - (float(distance) ** 2) / 2.0
    return max(0.0, min(1.0, sim))


def _why(snippet: str, keywords: list[str], services: list[str]) -> dict[str, Any]:
    low = snippet.lower()
    matched_kw = [k for k in keywords if k.lower() in low]
    ents = extract_entities(snippet, service_vocab=services)
    return {
        "matched_keywords": matched_kw,
        "mentioned_services": ents["services"],
        "jira_keys": ents["jira_keys"],
        "pr_refs": ents["pr_refs"],
    }


def topic_scan(watchlist_id: str, *, k: int = 8, min_similarity: float = 0.3) -> dict[str, Any]:
    """Scan one watchlist and return ranked hit cards.

    Args:
        watchlist_id:   id from watchlists.yaml.
        k:              max cards.
        min_similarity: drop hits below this cosine similarity.

    Returns:
        {watchlist, title, cards:[{source,ref,title,similarity,excerpt,why}], count}
    """
    wl = get_watchlist(watchlist_id)
    if wl is None:
        ids = [w.id for w in load_watchlists()]
        return {"error": f"unknown watchlist '{watchlist_id}'", "available": ids}

    query = wl.query_text or wl.title
    # Scope retrieval to the watchlist's declared sources; None ⇒ all sources.
    sources = wl.sources or [None]  # type: ignore[list-item]

    seen: set[str] = set()
    cards: list[dict[str, Any]] = []
    for src in sources:
        for h in retrieve(query, k=k, source=src):
            if h["id"] in seen:
                continue
            seen.add(h["id"])
            sim = _similarity(h["distance"])
            if sim < min_similarity:
                continue
            meta = h.get("meta") or {}
            cards.append({
                "source": h["source"],
                "ref": h["ref"],
                "title": meta.get("title") or meta.get("summary") or "",
                "similarity": round(sim, 3),
                "excerpt": (h.get("text") or "")[:280],
                "why": _why(h.get("text") or "", wl.keywords, wl.services),
            })

    cards.sort(key=lambda c: c["similarity"], reverse=True)
    cards = cards[:k]
    return {"watchlist": wl.id, "title": wl.title, "count": len(cards), "cards": cards}


@SPROUT.task()
@log_result()
def topic_scan_task(**kwargs):
    """Celery wrapper for topic_scan(). Args: watchlist_id, k, min_similarity."""
    return topic_scan(
        watchlist_id=kwargs.get("watchlist_id", ""),
        k=int(kwargs.get("k", 8)),
        min_similarity=float(kwargs.get("min_similarity", 0.3)),
    )
