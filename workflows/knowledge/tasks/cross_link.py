"""
workflows/knowledge/tasks/cross_link.py

Phase-3 cross-source intelligence — the "second brain" layer on top of the
single-store RAG retriever. Where Phase 1 answers "what do the docs say?", this
answers the questions a person in a large org actually has:

  * working_context() — "Given what I've been doing (HFL + recent signals),
    what indexed knowledge is relevant right now?"  → infers current focus and
    pulls the docs/tickets/PRs that connect to it.
  * relations()       — "Show me how this topic connects across teams." → a
    small graph of items (Confluence/Jira/GitHub/HFL) linked by shared entities
    (Jira keys, service names) and semantic similarity.
  * orphan_jira()     — "Which tickets have no matching doc?" → likely
    undocumented work / knowledge gaps.
  * stale_docs()      — "Which docs look stale versus the code?" → pages that
    semantically match a closed/merged PR — verify they still reflect reality.

Everything is grounded: every finding carries the source refs it came from.
The Anthropic summary (working_context summarize=True) is optional and pinned
to Haiku for cost, per the project convention.
"""

from __future__ import annotations

from typing import Any, Optional

from core.apps.sprout.app.celery import SPROUT
from core.apps.es_logging.app.elasticsearch import log_result
from core.utilities.logging.custom_logger import create_logger

from apps.sqlite_vec import store

from workflows.knowledge.entities import extract_entities, shared_entities
from workflows.knowledge.retriever import retrieve, format_context
from workflows.knowledge.watchlist import all_services

_log = create_logger("knowledge.cross_link")

_DEFAULT_HAIKU = "claude-haiku-4-5-20251001"
_MAX_QUERY_CHARS = 2000  # cap the synthesised query we send to the embedder


def _similarity(distance: float) -> float:
    """L2 distance over L2-normalised vectors → cosine similarity in [0, 1].

    distance = sqrt(2 - 2·cos)  ⇒  cos = 1 - distance²/2. Clamped to [0, 1].
    """
    sim = 1.0 - (float(distance) ** 2) / 2.0
    return max(0.0, min(1.0, sim))


def _annotate(hit: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": hit["id"],
        "source": hit["source"],
        "ref": hit["ref"],
        "title": (hit.get("meta") or {}).get("title") or (hit.get("meta") or {}).get("summary") or "",
        "similarity": round(_similarity(hit["distance"]), 3),
        "excerpt": (hit.get("text") or "")[:280],
        "text": hit.get("text") or "",
    }


def _recent_signals(since: str, limit: int) -> list[dict[str, Any]]:
    """Recent HFL entries (ES first, corpus fallback) — your captured activity."""
    try:
        from workflows.hfl.es_store import query_hfl_entries
        rows = query_hfl_entries(since=since, limit=limit)
        if rows:
            return [{
                "when": r.get("entry_date") or r.get("when"),
                "moment": r.get("moment") or "",
                "what_happened": r.get("what_happened") or "",
                "tags": r.get("tags") or [],
                "references": r.get("references") or [],
                "source": r.get("source") or "hfl",
            } for r in rows]
    except Exception as exc:  # noqa: BLE001
        _log.warning("cross_link: HFL ES query failed (%s) — trying corpus", exc)
    try:
        from workflows.hfl.tasks.retrieve import retrieve_hfl_corpus
        res = retrieve_hfl_corpus(since=since, k=limit)
        return [{
            "when": h.get("date"),
            "moment": h.get("header") or "",
            "what_happened": h.get("body") or "",
            "tags": [],
            "references": [],
            "source": "hfl-corpus",
        } for h in (res.get("hits") or [])]
    except Exception as exc:  # noqa: BLE001
        _log.warning("cross_link: HFL corpus retrieve failed (%s)", exc)
        return []


def _signal_text(signals: list[dict[str, Any]]) -> str:
    parts: list[str] = []
    for s in signals:
        parts.append(s.get("moment", ""))
        if s.get("what_happened"):
            parts.append(s["what_happened"])
        if s.get("references"):
            parts.append(" ".join(s["references"]))
    return "\n".join(p for p in parts if p)[:_MAX_QUERY_CHARS]


def _haiku_brief(system_prompt: str, user_msg: str, model: str) -> str:
    """Best-effort Anthropic summary. Returns '' on any failure (never raises)."""
    try:
        from apps.antropic.config import get_config as get_anthropic_config
        from apps.antropic.references.web.base_api_service import BaseApiServiceAnthropic
        client = BaseApiServiceAnthropic(get_anthropic_config("ANTHROPIC"))
        if not client.base_client:
            return ""
        resp = client.send_messages(
            messages=[{"role": "user", "content": user_msg}],
            model=model, max_tokens=700, system=system_prompt,
        )
        return resp.content[0].text.strip() if resp.content else ""
    except Exception as exc:  # noqa: BLE001
        _log.warning("cross_link: Anthropic brief failed (%s)", exc)
        return ""


# --------------------------------------------------------------------------- #
# working_context — infer current focus, surface related knowledge
# --------------------------------------------------------------------------- #

def working_context(
    *,
    since: str = "-3d",
    k: int = 8,
    summarize: bool = False,
    model: str = _DEFAULT_HAIKU,
) -> dict[str, Any]:
    """Infer what you're working on from recent HFL signal and surface the
    indexed knowledge that connects to it.

    Args:
        since:     Window for recent signals (ISO date or relative "-Nd").
        k:         How many signals to read and how many related hits to return.
        summarize: If True, add a short Anthropic brief tying it together.
        model:     Anthropic model for the brief (default Haiku 4.5).

    Returns:
        {focus_signals, related, referenced_items, entities, brief}
    """
    signals = _recent_signals(since, k)
    if not signals:
        return {"focus_signals": [], "related": [], "referenced_items": [],
                "entities": {}, "brief": "", "note": "no recent HFL signal in window"}

    text = _signal_text(signals)
    vocab = all_services()
    entities = extract_entities(text, service_vocab=vocab)

    related = [_annotate(h) for h in retrieve(text, k=k)] if text else []

    # Explicit references in your activity → pull the indexed item directly.
    referenced_items: list[dict[str, Any]] = []
    for key in (entities.get("jira_keys", []) + entities.get("pr_refs", []))[:10]:
        hits = retrieve(key, k=1)
        if hits and _similarity(hits[0]["distance"]) > 0.4:
            ref = _annotate(hits[0])
            ref["matched_entity"] = key
            referenced_items.append(ref)

    brief = ""
    if summarize:
        ctx = format_context([
            {"ref": r["ref"], "text": r["text"], "id": r["id"]} for r in related
        ])
        recent = "\n".join(f"- {s['when']}: {s['moment']}" for s in signals)
        brief = _haiku_brief(
            "You connect a person's recent work to the team's indexed knowledge. "
            "Be concise. Name the apparent current focus in one line, then list the "
            "2-4 most relevant docs/tickets/PRs and WHY each matters, with [n] "
            "citations referring to the context blocks. Flag anything that looks "
            "stale or contradictory.",
            f"My recent activity:\n{recent}\n\nRelated indexed knowledge:\n\n{ctx}",
            model,
        )

    return {
        "focus_signals": signals,
        "related": related,
        "referenced_items": referenced_items,
        "entities": entities,
        "brief": brief,
    }


# --------------------------------------------------------------------------- #
# relations — a small cross-source graph around a topic/entity
# --------------------------------------------------------------------------- #

def relations(query: str, *, k: int = 12, per_source: bool = True) -> dict[str, Any]:
    """Build a relation graph for a topic or entity across all sources.

    Nodes are the top retrieved chunks; edges are drawn between two nodes when
    they share an explicit entity (Jira key / service / PR ref) — the strongest
    "these are about the same thing" signal — annotated with what they share.

    Args:
        query:      Topic string or an entity like 'PAY-1421' or 'Payments'.
        k:          Total nodes to consider.
        per_source: If True, top up retrieval per source so a single dominant
                    source can't crowd out cross-source links.

    Returns:
        {query, nodes, edges, by_source}
    """
    vocab = all_services()
    hits: list[dict[str, Any]] = []
    seen_ids: set[str] = set()

    if per_source:
        for src in ("confluence", "jira", "github", "gdrive", "notion"):
            for h in retrieve(query, k=max(2, k // 3), source=src):
                if h["id"] not in seen_ids:
                    seen_ids.add(h["id"])
                    hits.append(h)
    for h in retrieve(query, k=k):
        if h["id"] not in seen_ids:
            seen_ids.add(h["id"])
            hits.append(h)

    nodes = [_annotate(h) for h in hits]

    edges: list[dict[str, Any]] = []
    for i in range(len(nodes)):
        for j in range(i + 1, len(nodes)):
            a, b = nodes[i], nodes[j]
            shared = shared_entities(a["text"], b["text"], service_vocab=vocab)
            if shared and a["source"] != b["source"]:
                edges.append({
                    "from": a["id"], "to": b["id"],
                    "from_source": a["source"], "to_source": b["source"],
                    "type": "shared_entity",
                    "shared": sorted(shared),
                })

    by_source: dict[str, int] = {}
    for n in nodes:
        by_source[n["source"]] = by_source.get(n["source"], 0) + 1

    # Strip bulky text from the returned nodes — callers want the map, not the corpus.
    for n in nodes:
        n.pop("text", None)

    return {"query": query, "nodes": nodes, "edges": edges, "by_source": by_source}


# --------------------------------------------------------------------------- #
# orphan_jira — tickets with no matching doc (knowledge gaps)
# --------------------------------------------------------------------------- #

def orphan_jira(*, min_doc_similarity: float = 0.55, limit: int = 50,
                doc_source: str = "confluence") -> dict[str, Any]:
    """Jira issues whose best documentation match is weak → likely undocumented.

    For each indexed Jira issue we query the doc source with the issue summary
    and check the best similarity. Below the threshold ⇒ flagged as an orphan.

    Args:
        min_doc_similarity: Similarity floor; below this is "no matching doc".
        limit:              Max issues to evaluate (cost guard).
        doc_source:         Which source counts as "documentation".

    Returns:
        {evaluated, orphans:[{issue_key, summary, ref, best_doc_similarity, best_doc_ref}]}
    """
    rows = store.get_meta_by_source("jira")
    # One row per chunk; collapse to one entry per issue (chunk_idx 0 carries summary).
    by_issue: dict[str, dict[str, Any]] = {}
    for r in rows:
        meta = r.get("meta") or {}
        key = meta.get("issue_key")
        if key and key not in by_issue:
            by_issue[key] = {"summary": meta.get("summary", ""), "ref": r.get("ref", "")}

    orphans: list[dict[str, Any]] = []
    evaluated = 0
    for key, info in list(by_issue.items())[:limit]:
        evaluated += 1
        query = f"{key} {info['summary']}".strip()
        hits = retrieve(query, k=1, source=doc_source)
        best_sim = _similarity(hits[0]["distance"]) if hits else 0.0
        if best_sim < min_doc_similarity:
            orphans.append({
                "issue_key": key,
                "summary": info["summary"],
                "ref": info["ref"],
                "best_doc_similarity": round(best_sim, 3),
                "best_doc_ref": hits[0]["ref"] if hits else None,
            })

    orphans.sort(key=lambda o: o["best_doc_similarity"])
    return {"evaluated": evaluated, "orphan_count": len(orphans),
            "doc_source": doc_source, "orphans": orphans}


# --------------------------------------------------------------------------- #
# stale_docs — docs that match shipped code (verify they're current)
# --------------------------------------------------------------------------- #

def stale_docs(*, min_code_similarity: float = 0.6, limit: int = 50,
               doc_source: str = "confluence", code_source: str = "github") -> dict[str, Any]:
    """Docs that closely match a CLOSED/MERGED PR — candidates for staleness.

    Heuristic: if a doc page semantically matches code that has already shipped,
    the doc may describe an older design. We surface the pair so a human can
    confirm. Not a verdict — a prompt to look.

    Args:
        min_code_similarity: Similarity floor for considering doc↔code a match.
        limit:               Max doc pages to evaluate.
        doc_source/code_source: source labels.

    Returns:
        {evaluated, candidates:[{page_id,title,ref,code_ref,code_state,similarity}]}
    """
    rows = store.get_meta_by_source(doc_source)
    by_page: dict[str, dict[str, Any]] = {}
    for r in rows:
        meta = r.get("meta") or {}
        pid = meta.get("page_id") or r["id"].split(":")[0]
        if pid not in by_page:
            by_page[pid] = {"title": meta.get("title", ""), "ref": r.get("ref", "")}

    candidates: list[dict[str, Any]] = []
    evaluated = 0
    for pid, info in list(by_page.items())[:limit]:
        evaluated += 1
        hits = retrieve(info["title"] or pid, k=1, source=code_source)
        if not hits:
            continue
        sim = _similarity(hits[0]["distance"])
        meta = hits[0].get("meta") or {}
        state = (meta.get("state") or "").lower()
        is_shipped = state in ("closed", "merged") or bool(meta.get("merged"))
        if sim >= min_code_similarity and is_shipped:
            candidates.append({
                "page_id": pid,
                "title": info["title"],
                "ref": info["ref"],
                "code_ref": hits[0]["ref"],
                "code_state": meta.get("state"),
                "code_kind": meta.get("kind"),
                "similarity": round(sim, 3),
            })

    candidates.sort(key=lambda c: c["similarity"], reverse=True)
    return {"evaluated": evaluated, "candidate_count": len(candidates),
            "doc_source": doc_source, "code_source": code_source,
            "candidates": candidates}


# --------------------------------------------------------------------------- #
# Celery wrappers
# --------------------------------------------------------------------------- #

@SPROUT.task()
@log_result()
def cross_link_report(**kwargs):
    """Run the full cross-source pass and return one report. Schedulable.

    Args: since, k, min_doc_similarity, min_code_similarity, limit, summarize, model.
    """
    since = kwargs.get("since", "-7d")
    k = int(kwargs.get("k", 8))
    return {
        "working_context": working_context(
            since=since, k=k,
            summarize=bool(kwargs.get("summarize", False)),
            model=kwargs.get("model", _DEFAULT_HAIKU),
        ),
        "orphan_jira": orphan_jira(
            min_doc_similarity=float(kwargs.get("min_doc_similarity", 0.55)),
            limit=int(kwargs.get("limit", 50)),
        ),
        "stale_docs": stale_docs(
            min_code_similarity=float(kwargs.get("min_code_similarity", 0.6)),
            limit=int(kwargs.get("limit", 50)),
        ),
    }
