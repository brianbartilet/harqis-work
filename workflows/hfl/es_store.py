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

Hard contract — never break the beat:
  - index_hfl_entry: any ES/auth/network failure is logged at WARNING and
    swallowed. The corpus write already happened; ES is bonus.
  - query_hfl_entries: compatibility wrapper returning [] on failure.
  - query_hfl_entries_status: distinguishes an unavailable projection from
    a successful query with no matches.
  - Idempotent: canonical entry ids are required, so a re-run upserts.

Reuses the ELASTIC_LOGGING app config (URL/auth) that @log_result already
relies on — no new credentials. Index name: env HFL_ES_INDEX, default
"harqis-hfl-entries".
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Optional
from urllib.parse import quote, urljoin

from core.utilities.logging.custom_logger import create_logger

from workflows.hfl.dto import HflEntry

_log = create_logger("hfl.es_store")

_DEFAULT_INDEX = "harqis-hfl-entries"
HFL_ES_SCHEMA_VERSION = 1
_MAX_QUERY_LIMIT = 500


def _index_name() -> str:
    return os.environ.get("HFL_ES_INDEX", "").strip() or _DEFAULT_INDEX


def hfl_document(entry: HflEntry, source: str) -> dict[str, Any]:
    """HflEntry → ES document. Entry time is `when`/`entry_date`; post()
    injects its own `date` (index time) so the two never collide."""
    return {
        "schema_version": HFL_ES_SCHEMA_VERSION,
        "indexed_at": datetime.now(timezone.utc).isoformat(),
        "source": (source or "unknown").strip() or "unknown",
        "when": entry.when.isoformat() if entry.when else None,
        "entry_date": entry.when.strftime("%Y-%m-%d") if entry.when else None,
        "moment": entry.moment,
        "what_happened": entry.what_happened,
        "why_it_stayed": entry.why_it_stayed,
        "possible_use": entry.possible_use,
        "tags": list(entry.tags),
        "references": list(entry.references),
        "machine": entry.machine or None,
        "entry_id": entry.entry_id or None,
        "synthesized": False,
    }


def index_hfl_entry(
    entry: HflEntry,
    *,
    source: str,
    synthesized: bool = False,
    doc_id: Optional[str] = None,
) -> Optional[str]:
    """Index one HFL entry into the ES entry index. Best-effort.

    Returns the doc id on success, None on skip/failure (never raises).
    An empty `moment` is a no-op — mirrors capture's "smallest useful
    entry is one line" rule so empty entries don't pollute the index.

    `doc_id` may override the entry's canonical id for stable aggregate
    projections. Entries without either id are rejected: moment-derived ids
    can overwrite distinct entries and are not safe at scale.
    """
    if not entry.moment.strip():
        return None
    doc_id = (doc_id or entry.entry_id or "").strip()
    if not doc_id:
        _log.warning(
            "hfl.es_store: skipped entry without canonical id (source=%s)",
            source,
        )
        return None
    try:
        # Imported lazily: the es_logging module resolves ELASTIC_LOGGING
        # config at import time; keep that cost off the hot import path and
        # contained where we already handle its failure.
        from core.apps.es_logging.app.elasticsearch import post

        doc = hfl_document(entry, source)
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


@dataclass(frozen=True)
class HflQueryResult:
    """Observable search result; unavailable is distinct from zero matches."""

    rows: tuple[dict[str, Any], ...]
    available: bool
    error: str | None = None


def _exact_filter(field: str, value: str) -> dict[str, Any]:
    """Match both the explicit mapping and legacy dynamic `.keyword` fields."""
    return {
        "bool": {
            "should": [
                {"term": {field: value}},
                {"term": {f"{field}.keyword": value}},
            ],
            "minimum_should_match": 1,
        }
    }


def _search(body: dict[str, Any]) -> list[dict[str, Any]]:
    """Run a complete ES search body using the shared authenticated session."""
    from core.apps.es_logging.app.elasticsearch import _es_session

    session, base = _es_session()
    index = quote(_index_name(), safe="-_.")
    response = session.post(
        urljoin(base, f"{index}/_search"),
        json=body,
        timeout=20,
    )
    if response.status_code not in (200, 201):
        raise RuntimeError(f"Elasticsearch search returned HTTP {response.status_code}")
    hits = response.json().get("hits", {}).get("hits", [])
    return [
        hit["_source"]
        for hit in hits
        if isinstance(hit, dict) and isinstance(hit.get("_source"), dict)
    ]


def query_hfl_entries_status(
    *,
    query: str = "",
    since: Optional[str] = None,
    until: Optional[str] = None,
    tags: Optional[list[str]] = None,
    source: Optional[str] = None,
    limit: int = 50,
) -> HflQueryResult:
    """Query the HFL index and preserve availability information.

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
            filt.append(_exact_filter("tags", t))

    if source and source.strip():
        filt.append(_exact_filter("source", source.strip()))

    requested = min(_MAX_QUERY_LIMIT, max(1, int(limit)))
    es_query = {
        "bool": {
            "must": must or [{"match_all": {}}],
            "filter": filt,
        }
    }
    sort = (
        [{"_score": "desc"}, {"when": "desc"}, {"entry_id": "asc"}]
        if must
        else [{"when": "desc"}, {"entry_id": "asc"}]
    )
    body = {
        "query": es_query,
        "size": requested,
        "sort": sort,
        "track_total_hits": False,
    }
    try:
        return HflQueryResult(tuple(_search(body)), available=True)
    except Exception as exc:  # noqa: BLE001 - caller chooses fallback behaviour
        _log.warning("hfl.es_store: query failed (%s)", exc)
        return HflQueryResult((), available=False, error="elasticsearch_unavailable")


def query_hfl_entries(
    *,
    query: str = "",
    since: Optional[str] = None,
    until: Optional[str] = None,
    tags: Optional[list[str]] = None,
    source: Optional[str] = None,
    limit: int = 50,
) -> list[dict[str, Any]]:
    """Compatibility wrapper returning rows, or [] when ES is unavailable."""
    result = query_hfl_entries_status(
        query=query,
        since=since,
        until=until,
        tags=tags,
        source=source,
        limit=limit,
    )
    return list(result.rows)
