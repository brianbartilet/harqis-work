"""
workflows/hfl/es_store.py

The HFL Elasticsearch entry index — write + read, in one cohesive module.

HFL entries have always been a Markdown corpus (one file per day; see
workflows/hfl/tasks/capture.py). This module adds a parallel, *queryable*
projection: each entry is also indexed as a structured document so it can
be retrieved by window/query/tags (the memory_recall_es MCP tool) and, in
future, fed to the knowledge RAG pipeline. The corpus stays the source of
truth — this index is additive and best-effort.

Manifesto note (docs/MANIFESTO.md §1): this is the "Distill → structured
DTO" step plus a second Express path (ES retrieval) for every captured
entry, so dual-written entries are never write-only dead weight.

Hard contract — never break the beat or an MCP call:
  - index_hfl_entry: any ES/auth/network failure is logged at WARNING and
    swallowed. The corpus write already happened; ES is bonus.
  - query_hfl_entries: any failure returns [] (callers no-op cleanly).
  - Idempotent: the doc id is deterministic (date+moment+source), so a
    re-run upserts rather than duplicating.

Reuses the ELASTIC_LOGGING app config (URL/auth) that @log_result already
relies on — no new credentials. Index name: env HFL_ES_INDEX, default
"harqis-hfl-entries".
"""

from __future__ import annotations

import hashlib
import os
from datetime import date, datetime
from typing import Any, Optional

from core.utilities.logging.custom_logger import create_logger

from workflows.hfl.dto import HflEntry

_log = create_logger("hfl.es_store")

_DEFAULT_INDEX = "harqis-hfl-entries"


def _index_name() -> str:
    return os.environ.get("HFL_ES_INDEX", "").strip() or _DEFAULT_INDEX


def _doc_id(entry: HflEntry, source: str) -> str:
    """Deterministic id so re-ingesting the same moment upserts, not dupes.

    date + a short hash of the moment + source. Stable across runs because
    every component is derived from the entry content, not wall-clock.
    """
    day = entry.when.strftime("%Y%m%d") if entry.when else "00000000"
    moment_hash = hashlib.sha1(
        (entry.moment or "").strip().lower().encode("utf-8")
    ).hexdigest()[:12]
    src = (source or "unknown").strip().lower().replace(" ", "-") or "unknown"
    return f"{day}-{src}-{moment_hash}"


def _to_doc(entry: HflEntry, source: str) -> dict[str, Any]:
    """HflEntry → ES document. Entry time is `when`/`entry_date`; post()
    injects its own `date` (index time) so the two never collide."""
    return {
        "source": (source or "unknown").strip() or "unknown",
        "when": entry.when.isoformat() if entry.when else None,
        "entry_date": entry.when.strftime("%Y-%m-%d") if entry.when else None,
        "moment": entry.moment,
        "what_happened": entry.what_happened,
        "why_it_stayed": entry.why_it_stayed,
        "possible_use": entry.possible_use,
        "tags": list(entry.tags),
        "references": list(entry.references),
        "synthesized": False,
    }


def index_hfl_entry(
    entry: HflEntry,
    *,
    source: str,
    synthesized: bool = False,
) -> Optional[str]:
    """Index one HFL entry into the ES entry index. Best-effort.

    Returns the doc id on success, None on skip/failure (never raises).
    An empty `moment` is a no-op — mirrors capture's "smallest useful
    entry is one line" rule so empty entries don't pollute the index.
    """
    if not entry.moment.strip():
        return None
    doc_id = _doc_id(entry, source)
    try:
        # Imported lazily: the es_logging module resolves ELASTIC_LOGGING
        # config at import time; keep that cost off the hot import path and
        # contained where we already handle its failure.
        from core.apps.es_logging.app.elasticsearch import post

        doc = _to_doc(entry, source)
        doc["synthesized"] = bool(synthesized)
        post(
            doc,
            _index_name(),
            location_key=doc_id,
            use_interval_map=False,   # deterministic id → upsert, no suffix
        )
        _log.info("hfl.es_store: indexed %s (source=%s)", doc_id, source)
        return doc_id
    except Exception as exc:  # noqa: BLE001 - ES is bonus; corpus already won
        _log.warning(
            "hfl.es_store: index failed for %s (%s) — corpus entry is "
            "unaffected", doc_id, exc,
        )
        return None


def _parse_day(value: Optional[str]) -> Optional[str]:
    """Normalise a since/until bound to YYYY-MM-DD, or None."""
    if not value:
        return None
    s = str(value).strip()
    if s.startswith("-") and s.endswith("d"):
        try:
            from datetime import timedelta
            n = int(s[1:-1])
            return (datetime.now() - timedelta(days=n)).strftime("%Y-%m-%d")
        except ValueError:
            return None
    try:
        return datetime.fromisoformat(s).strftime("%Y-%m-%d")
    except ValueError:
        return None


def query_hfl_entries(
    *,
    query: str = "",
    since: Optional[str] = None,
    until: Optional[str] = None,
    tags: Optional[list[str]] = None,
    source: Optional[str] = None,
    limit: int = 50,
) -> list[dict[str, Any]]:
    """Query the HFL entry index. Returns [] on any failure (never raises).

    Filters compose with AND:
      - since/until → range on `entry_date` (ISO or relative "-Nd")
      - tags        → every tag must be present (terms AND)
      - source      → exact source match
      - query       → free-text over moment/what_happened/why_it_stayed
    """
    must: list[dict] = []
    filt: list[dict] = []

    if query and query.strip():
        must.append({
            "multi_match": {
                "query": query.strip(),
                "fields": ["moment^2", "what_happened", "why_it_stayed",
                           "possible_use", "tags"],
            }
        })

    lo, hi = _parse_day(since), _parse_day(until)
    if lo or hi:
        rng: dict[str, str] = {}
        if lo:
            rng["gte"] = lo
        if hi:
            rng["lte"] = hi
        filt.append({"range": {"entry_date": rng}})

    for t in tags or []:
        t = str(t).strip().lstrip("#")
        if t:
            filt.append({"term": {"tags": t}})

    if source and source.strip():
        filt.append({"term": {"source": source.strip()}})

    body = {
        "bool": {
            "must": must or [{"match_all": {}}],
            "filter": filt,
        }
    }
    try:
        from core.apps.es_logging.app.elasticsearch import get_index_data

        hits = get_index_data(
            _index_name(),
            query=body,
            fetch_docs=max(1, int(limit)),
        )
        # get_index_data returns _source dicts (no type_hook passed).
        rows = [h for h in (hits or []) if isinstance(h, dict)]
        rows.sort(key=lambda r: r.get("entry_date") or "", reverse=True)
        return rows[: max(1, int(limit))]
    except Exception as exc:  # noqa: BLE001 - read failure → empty, caller no-ops
        _log.warning("hfl.es_store: query failed (%s) — returning []", exc)
        return []
