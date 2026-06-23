"""
workflows/knowledge/tasks/topic_map.py

"Help me learn a topic and see how it connects to everything else."

Given a topic, retrieve across every indexed source, extract the entities that
anchor it, and ask Anthropic for a structured learning brief — what it is, how
it works, its integrations & dependencies, the business value, related tickets/
docs/PRs, and what to learn next. Citation-first, grounded in the retrieved
context only.

This is the learner-facing complement to cross_link.relations() (which returns
the raw graph): topic_map() returns the *explanation*, with the graph's entities
and per-source hit list attached so the answer is auditable.

Pinned to Haiku 4.5 for cost (override per call). Do not raise the Anthropic
config default — pass model= instead.
"""

from __future__ import annotations

from typing import Any, Optional

from core.apps.sprout.app.celery import SPROUT
from core.apps.es_logging.app.elasticsearch import log_result
from core.utilities.logging.custom_logger import create_logger

from apps.antropic.config import get_config as get_anthropic_config
from apps.antropic.references.web.base_api_service import BaseApiServiceAnthropic

from workflows.knowledge.entities import extract_entities
from workflows.knowledge.prompts import load_prompt
from workflows.knowledge.retriever import retrieve, format_context
from workflows.knowledge.watchlist import all_services

_log = create_logger("knowledge.topic_map")

_DEFAULT_HAIKU = "claude-haiku-4-5-20251001"


def topic_map(
    topic: str,
    *,
    k: int = 12,
    model: str = _DEFAULT_HAIKU,
    max_tokens: int = 1200,
) -> dict[str, Any]:
    """Build a cited learning brief for `topic` across all indexed sources.

    Args:
        topic:      The thing to learn, e.g. "OAuth token refresh" or "Payments
                    settlement flow".
        k:          Total snippets to retrieve (topped up per source so one
                    corpus doesn't dominate).
        model:      Anthropic model (default Haiku 4.5).
        max_tokens: Generation cap.

    Returns:
        {topic, brief, hits, by_source, entities, model}
    """
    if not topic.strip():
        return {"topic": topic, "brief": "", "hits": [], "by_source": {},
                "entities": {}, "model": model, "error": "empty topic"}

    # Retrieve broadly, topping up per source for cross-team coverage.
    hits: list[dict[str, Any]] = []
    seen: set[str] = set()
    for src in ("confluence", "jira", "github", "gdrive", "notion"):
        for h in retrieve(topic, k=max(2, k // 4), source=src):
            if h["id"] not in seen:
                seen.add(h["id"])
                hits.append(h)
    for h in retrieve(topic, k=k):
        if h["id"] not in seen:
            seen.add(h["id"])
            hits.append(h)

    if not hits:
        return {"topic": topic, "brief": f"Nothing indexed yet for '{topic}'.",
                "hits": [], "by_source": {}, "entities": {}, "model": model}

    # Rank by similarity (smallest distance first) and keep the strongest k.
    hits.sort(key=lambda h: h["distance"])
    hits = hits[:k]

    joined_text = "\n".join(h.get("text", "") for h in hits)
    entities = extract_entities(joined_text, service_vocab=all_services())

    by_source: dict[str, int] = {}
    for h in hits:
        by_source[h["source"]] = by_source.get(h["source"], 0) + 1

    context = format_context(hits)
    system_prompt = load_prompt("topic_map")
    user_msg = f"Topic: {topic}\n\nContext snippets:\n\n{context}"

    client = BaseApiServiceAnthropic(get_anthropic_config("ANTHROPIC"))
    if not client.base_client:
        raise RuntimeError("Anthropic client failed to initialize")
    response = client.send_messages(
        messages=[{"role": "user", "content": user_msg}],
        model=model, max_tokens=max_tokens, system=system_prompt,
    )
    brief = response.content[0].text.strip() if response.content else ""

    return {
        "topic": topic,
        "brief": brief,
        "hits": [
            {"id": h["id"], "source": h["source"], "ref": h["ref"],
             "title": (h.get("meta") or {}).get("title")
                      or (h.get("meta") or {}).get("summary") or "",
             "distance": round(h["distance"], 4)}
            for h in hits
        ],
        "by_source": by_source,
        "entities": entities,
        "model": model,
    }


@SPROUT.task()
@log_result()
def topic_map_task(**kwargs):
    """Celery wrapper for topic_map(). Args: topic, k, model, max_tokens."""
    return topic_map(
        topic=kwargs.get("topic", ""),
        k=int(kwargs.get("k", 12)),
        model=kwargs.get("model", _DEFAULT_HAIKU),
        max_tokens=int(kwargs.get("max_tokens", 1200)),
    )
