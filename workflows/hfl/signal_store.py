"""
workflows/hfl/signal_store.py

The HFL *signal buffer* — a lightweight, per-task-run capture that feeds the
daily HFL rollup (Option B; see docs/thesis/HFL-AUTO-EXPRESS.md).

The task_success hook (workflows/hfl/express_signals.py) appends one cheap,
no-LLM signal record here for every task whose manifesto declares
``hfl_express: 'buffer'``. A daily rollup task (Phase 2) reads the day's
signals, groups them by source, and distills them into proper HFL entries via
the existing ``es_store.index_hfl_entry`` pipeline.

This is the Capture half of CODE applied to task output: cheap and frequent
here, distilled and daily downstream — so the corpus stays story-grained while
capture stays comprehensive. The buffer is NOT the corpus; it is a staging
index the rollup drains.

Reuses the ELASTIC_LOGGING app config (same as es_store / @log_result) — no new
credentials. Index name: env ``HFL_SIGNALS_ES_INDEX``, default
``harqis-hfl-signals``.

Hard contract: ``index_hfl_signal`` is best-effort and NEVER raises — it runs
*after* a task already succeeded, so a buffer-write failure must not turn a
green run red. ``query_hfl_signals`` returns [] on any failure.
"""

from __future__ import annotations

import hashlib
import os
from datetime import datetime, timedelta
from typing import Any, Optional

from core.utilities.logging.custom_logger import create_logger

_log = create_logger("hfl.signal_store")

_DEFAULT_INDEX = "harqis-hfl-signals"
_MAX_SUMMARY = 1000


def _index_name() -> str:
    return os.environ.get("HFL_SIGNALS_ES_INDEX", "").strip() or _DEFAULT_INDEX


def _doc_id(task: str, when: datetime, dedup_key: str) -> str:
    """Deterministic id so a task retry (or a broadcast re-fire) that produces
    the same output in the same minute upserts rather than duplicates.

    minute-bucketed timestamp + task + a short hash of ``dedup_key``. Distinct
    runs at distinct minutes (or with distinct output) get distinct ids and are
    all preserved for the daily rollup.
    """
    ts = when.strftime("%Y%m%dT%H%M") if when else "00000000T0000"
    h = hashlib.sha1((dedup_key or "").encode("utf-8")).hexdigest()[:10]
    t = (task or "unknown").strip().lower().replace(" ", "-") or "unknown"
    return f"{ts}-{t}-{h}"


def index_hfl_signal(
    *,
    task: str,
    source: str,
    summary: str,
    status: str = "success",
    when: Optional[datetime] = None,
    references: Optional[list[str]] = None,
    dedup_key: Optional[str] = None,
) -> Optional[str]:
    """Append one signal record to the HFL signal buffer. Best-effort.

    Returns the doc id on success, or None on skip/failure (never raises).
    An empty ``summary`` is a no-op — nothing to roll up.

    Args:
        task:       dotted task path (the producer).
        source:     rollup grouping key, e.g. ``"signal:get_schedules"``.
        summary:    short, no-LLM digest of the task output (truncated).
        status:     run status (``"success"`` for the task_success hook).
        when:       event time; defaults to now.
        references: optional source artifacts (e.g. the task's express_target),
                    carried through to the eventual entry's ``references``.
        dedup_key:  what makes two records "the same"; defaults to ``summary``.
    """
    if not (summary or "").strip():
        return None
    when = when or datetime.now()
    dedup_key = dedup_key if dedup_key is not None else summary
    doc_id = _doc_id(task, when, dedup_key)
    try:
        # Imported lazily — es_logging resolves ELASTIC_LOGGING config at import
        # time; keep that cost contained where its failure is already handled.
        from core.apps.es_logging.app.elasticsearch import post

        doc = {
            "task": task,
            "source": (source or "unknown").strip() or "unknown",
            "summary": summary.strip()[:_MAX_SUMMARY],
            "status": status,
            "when": when.isoformat(),
            "entry_date": when.strftime("%Y-%m-%d"),
            "references": list(references or []),
            "rolled_up": False,   # Phase 2 sets this when the rollup drains it
        }
        post(
            doc,
            _index_name(),
            location_key=doc_id,
            use_interval_map=False,   # deterministic id → upsert, no suffix
        )
        _log.info("hfl.signal_store: buffered %s (task=%s)", doc_id, task)
        return doc_id
    except Exception as exc:  # noqa: BLE001 - buffer is bonus; the task already won
        _log.warning(
            "hfl.signal_store: buffer write failed for %s (%s) — the task "
            "result is unaffected", task, exc,
        )
        return None


def _parse_day(value: Optional[str]) -> Optional[str]:
    """Normalise a since/until bound to YYYY-MM-DD, or None. Mirrors es_store."""
    if not value:
        return None
    s = str(value).strip()
    if s.startswith("-") and s.endswith("d"):
        try:
            n = int(s[1:-1])
            return (datetime.now() - timedelta(days=n)).strftime("%Y-%m-%d")
        except ValueError:
            return None
    try:
        return datetime.fromisoformat(s).strftime("%Y-%m-%d")
    except ValueError:
        return None


def query_hfl_signals(
    *,
    since: Optional[str] = None,
    until: Optional[str] = None,
    source: Optional[str] = None,
    include_rolled_up: bool = False,
    limit: int = 1000,
) -> list[dict[str, Any]]:
    """Read buffered signals for the daily rollup (Phase 2). [] on any failure.

    Filters compose with AND:
      - since/until → range on ``entry_date`` (ISO or relative "-Nd")
      - source      → exact source match
      - include_rolled_up → when False (default) only undrained signals
    """
    filt: list[dict] = []

    lo, hi = _parse_day(since), _parse_day(until)
    if lo or hi:
        rng: dict[str, str] = {}
        if lo:
            rng["gte"] = lo
        if hi:
            rng["lte"] = hi
        filt.append({"range": {"entry_date": rng}})

    if source and source.strip():
        filt.append({"term": {"source": source.strip()}})

    if not include_rolled_up:
        filt.append({"term": {"rolled_up": False}})

    body = {"bool": {"must": [{"match_all": {}}], "filter": filt}}
    try:
        from core.apps.es_logging.app.elasticsearch import get_index_data

        hits = get_index_data(_index_name(), query=body, fetch_docs=max(1, int(limit)))
        rows = [h for h in (hits or []) if isinstance(h, dict)]
        rows.sort(key=lambda r: r.get("when") or "", reverse=True)
        return rows[: max(1, int(limit))]
    except Exception as exc:  # noqa: BLE001 - read failure → empty, caller no-ops
        _log.warning("hfl.signal_store: query failed (%s) — returning []", exc)
        return []
