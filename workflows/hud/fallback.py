"""
workflows/hud/fallback.py

Host-side machinery for the HUD **data-only fallback** (see the
`/create-data-only-from-hud` skill). HUD render tasks run only on the Windows
`hud` queue; when that box is offline the always-on host runs a *data-only
twin* so the ``@feed`` dump + ``@log_result`` Elasticsearch record keep flowing.

The twin gates on a HEARTBEAT it gets for free: every HUD task already carries
``@log_result``, which upserts ONE doc per task into the
``harqis-elastic-logging`` index keyed by ``name = "<module>.<qualname>"`` with
a ``date`` field = last run time. If that date is fresh (within
``max_staleness_secs``), Windows handled it → the twin short-circuits. If it's
stale or missing, the twin runs the collector.

This module is **win32-free** — it imports only the ES logging lib (lazily) +
stdlib, so it is safe to import on the macOS/Linux host. The ``hud_*.py`` render
modules are NOT (they pull in Rainmeter/win32 and are import-guarded to win32 in
``workflows/hud/__init__.py``); collectors and this gate deliberately avoid that.
"""
from __future__ import annotations

import functools
from datetime import datetime
from typing import Any, Callable, Optional

from core.utilities.logging.custom_logger import logger as log

# Index @log_result writes to. Mirrors core.apps.es_logging.app.elasticsearch
# (LOGGING_INDEX). Kept as a literal so importing this module never triggers the
# ES config load at worker-import time.
_HEARTBEAT_INDEX = "harqis-elastic-logging"

# @log_result stores `date` at minute precision (ELASTIC_TIME_FORMAT default
# "%Y-%m-%dT%H:%M"); tolerate second/microsecond precision too in case the
# index format is overridden.
_HEARTBEAT_TIME_FORMATS = (
    "%Y-%m-%dT%H:%M",
    "%Y-%m-%dT%H:%M:%S",
    "%Y-%m-%dT%H:%M:%S.%f",
)


def _parse_heartbeat_date(raw: Optional[str]) -> Optional[datetime]:
    """Parse a `@log_result` date string (naive, worker-local). None on failure."""
    if not raw:
        return None
    for fmt in _HEARTBEAT_TIME_FORMATS:
        try:
            return datetime.strptime(raw, fmt)
        except (ValueError, TypeError):
            continue
    return None


def windows_handled_recently(
    original_task_name: str,
    max_staleness_secs: float,
    *,
    now: Optional[datetime] = None,
) -> bool:
    """True if ``original_task_name`` logged a run within ``max_staleness_secs``.

    Reads the single `@log_result` heartbeat doc (keyed by task name) and
    compares its ``date`` to now. Fetch-all-then-filter mirrors how
    ``log_result`` itself reads the index (one small doc per task).

    Fails **OPEN**: on any error (ES down, doc missing, unparseable date) returns
    ``False`` so the twin runs. A spurious extra run only costs one feed block +
    ES doc; a missed run loses the data — which is the whole thing we're avoiding.

    NOTE on time zones: both the heartbeat date and ``now`` are naive,
    worker-local timestamps. If the Windows box and the host run in different OS
    time zones the age is skewed by the offset; keep the staleness grace
    generous (cadence + a few minutes) so a modest skew can't mask a live worker.
    """
    now = now or datetime.now()
    try:
        # Lazy import: keeps this module importable without ES configured.
        from core.apps.es_logging.app.elasticsearch import get_index_data
        from core.apps.es_logging.models.document import DtoFunctionLogger

        docs = get_index_data(_HEARTBEAT_INDEX, type_hook=DtoFunctionLogger)
        match = next(
            (d for d in (docs or []) if getattr(d, "name", None) == original_task_name),
            None,
        )
        if match is None:
            log.info("hud-fallback: no heartbeat for %s — treating as stale", original_task_name)
            return False

        last = _parse_heartbeat_date(getattr(match, "date", None))
        if last is None:
            log.info("hud-fallback: unparseable heartbeat date for %s — treating as stale",
                     original_task_name)
            return False

        age = (now - last).total_seconds()
        fresh = age <= max_staleness_secs
        log.info(
            "hud-fallback: %s last ran %.0fs ago (threshold %.0fs) -> %s",
            original_task_name, age, max_staleness_secs,
            "fresh, skip twin" if fresh else "stale, run twin",
        )
        return fresh
    except Exception as e:
        log.warning(
            "hud-fallback: heartbeat check failed for %s (%s) — running twin",
            original_task_name, e,
        )
        return False


def fallback_gate(original_task_name: str, default_max_staleness_secs: float) -> Callable:
    """Decorator: run the wrapped data-only twin ONLY if the original HUD task
    hasn't logged a run within the staleness window.

    Placed OUTSIDE ``@log_result`` / ``@feed`` in the twin's decorator stack so a
    skip short-circuits *before* either sink fires — no empty feed block, no
    spurious twin ES doc on the cycles Windows is healthy.

    Two control kwargs are consumed here (popped, never forwarded to the
    collector):
      * ``force`` (bool)               — bypass the gate; always run. For manual
                                         triggering / testing.
      * ``max_staleness_secs`` (float) — override ``default_max_staleness_secs``
                                         per beat entry without editing code.
    """
    def deco(func: Callable) -> Callable:
        @functools.wraps(func)
        def wrapper(*args, **kwargs) -> Any:
            force = bool(kwargs.pop("force", False))
            staleness = kwargs.pop("max_staleness_secs", default_max_staleness_secs)
            if not force and windows_handled_recently(original_task_name, staleness):
                log.info("hud-fallback: %s handled by windows — skipping twin", original_task_name)
                return {"text": "", "summary": "skipped: windows handled recently", "skipped": True}
            return func(*args, **kwargs)
        return wrapper
    return deco
