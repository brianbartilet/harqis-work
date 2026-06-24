"""
workflows/hfl/express_signals.py

Option B / Phase 1: wire the manifesto ``hfl_express`` flag to the HFL signal
buffer. (Design: docs/thesis/HFL-AUTO-EXPRESS.md.)

A Celery ``task_success`` handler that, for any task whose manifesto declares
``hfl_express: 'buffer'``, appends one lightweight signal record to the HFL
signal buffer (workflows/hfl/signal_store.py) — no LLM, no corpus write. The
daily ``rollup_hfl_signals`` task (Phase 2) turns the day's buffered signals
into proper HFL entries via the existing ``es_store.index_hfl_entry`` pipeline.

Why a signal handler (not @log_result, not each task body):
  - @log_result lives in harqis-core; baking HFL into it would breach the
    migrate-to-core boundary (AI/HFL stays in harqis-work).
  - Editing every task body is invasive and easy to forget on new tasks.
  - One ``task_success`` receiver covers every current and future task, fires
    only on success, and runs after the task — it cannot break the beat.

The manifesto block lives in tasks_config.py (the beat-schedule entry) and is
stripped before Celery (workflows/config.py::_celery_safe_schedule), so we
recover it at runtime from ``CONFIG_DICTIONARY`` via a task-path → manifesto
map, built lazily and cached (lazy import avoids a circular dependency, since
workflows.config imports this module to connect the handler).

Hard contract: this runs AFTER a task already succeeded. Every failure is
caught and logged — expressing signal must never fail a green task. Tasks that
write their own HFL entries (the workflows/hfl/* ingestors) set
``hfl_express: 'self'`` or omit the field, and are skipped here.
"""

from __future__ import annotations

import json
from typing import Any, Optional

from celery.signals import task_success

from core.utilities.logging.custom_logger import create_logger

from workflows.hfl.signal_store import index_hfl_signal

_log = create_logger("hfl.express_signals")

_MAX_SUMMARY = 600

# Cached task-path → manifesto map (built once on first signal).
_map_cache: Optional[dict[str, dict]] = None


def _manifesto_map() -> dict[str, dict]:
    """Build (once) a dotted-task-path → manifesto block map from the beat
    schedule. Imported lazily: workflows.config imports THIS module at the
    bottom to connect the handler, so a top-level import would be circular."""
    global _map_cache
    if _map_cache is not None:
        return _map_cache
    out: dict[str, dict] = {}
    try:
        from workflows.config import CONFIG_DICTIONARY

        for entry in CONFIG_DICTIONARY.values():
            task = entry.get("task")
            man = entry.get("manifesto")
            if isinstance(task, str) and isinstance(man, dict):
                # Same task may appear under several beat entries (e.g. data-only
                # twins); their manifesto role is the same, so last-wins is fine.
                out[task] = man
    except Exception as exc:  # noqa: BLE001 - no map → handler simply no-ops
        _log.warning("hfl.express_signals: could not build manifesto map (%s)", exc)
    _map_cache = out
    return out


def manifesto_for(task_name: Optional[str]) -> Optional[dict]:
    """The manifesto block for a dotted task path, or None."""
    if not task_name:
        return None
    return _manifesto_map().get(task_name)


def _summarize(result: Any) -> str:
    """Collapse heterogeneous task output into one short, human-readable line
    (no LLM). The daily rollup is what turns these into real prose."""
    if result is None:
        return ""
    try:
        if isinstance(result, str):
            text = result
        elif isinstance(result, dict):
            text = json.dumps(result, default=str, ensure_ascii=False)
        else:
            text = str(result)
    except Exception:  # noqa: BLE001 - last-resort repr; never raise on summary
        text = repr(result)
    return " ".join(text.split())[:_MAX_SUMMARY]


def _short_name(task_name: str) -> str:
    """`workflows.hud.tasks.hud_logs.get_schedules` → `get_schedules`."""
    return (task_name or "").rsplit(".", 1)[-1] or "task"


def express_task_signal(task_name: Optional[str], result: Any) -> Optional[str]:
    """Buffer one signal for ``task_name`` iff its manifesto opts in with
    ``hfl_express: 'buffer'``. Returns the buffer doc id, or None when skipped.

    Separated from the signal wrapper so it is unit-testable without Celery.
    """
    man = manifesto_for(task_name)
    if not man or man.get("hfl_express") != "buffer":
        return None
    summary = _summarize(result)
    if not summary:
        return None
    ref = man.get("express_target")
    return index_hfl_signal(
        task=task_name,
        source=f"signal:{_short_name(task_name)}",
        summary=summary,
        status="success",
        references=[ref] if ref else None,
        dedup_key=summary,
    )


@task_success.connect
def _on_task_success(sender=None, result=None, **_):
    """Celery task_success receiver. Never raises — a green task stays green."""
    try:
        express_task_signal(getattr(sender, "name", None), result)
    except Exception as exc:  # noqa: BLE001 - post-success hook must not fail the task
        _log.warning("hfl.express_signals: express hook failed (%s)", exc)
