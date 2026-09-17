"""Content-free, model-free warning for unprocessed durable captures."""

from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from core.apps.es_logging.app.elasticsearch import log_result
from core.apps.sprout.app.celery import SPROUT
from workflows.hfl.tasks.analyze_media import (
    _filter_media_candidates_by_source,
    _filter_processed_media,
    _select_media_candidates,
    get_dumps_target,
    iter_recent_files,
    resolve_corpus_dir,
)
from workflows.hfl.tasks.check_activity_corpus_sources import _notify_telegram


def _monitor_pending_captures(
    *, window_days: int = 14, warning_threshold: int = 25,
    critical_threshold: int = 100, notify: bool = True,
) -> dict[str, Any]:
    """Count eligible, unclaimed captures; never treat missing storage as healthy.

    Completed semantic skips and active claims use the analyzer's shared state.
    Counts cover only the stated rolling window, not all retained history.
    Notification failures propagate rather than reporting a successful alert.
    """
    if window_days < 1 or not 1 <= warning_threshold <= critical_threshold:
        raise ValueError("positive window and 1 <= warning <= critical required")
    target = get_dumps_target()
    if not target or not Path(target.inbox).expanduser().is_dir():
        raise RuntimeError("Pending-capture monitor requires an accessible dumps inbox")
    corpus = resolve_corpus_dir()
    if not corpus.is_dir():
        raise RuntimeError("Pending-capture monitor requires an accessible corpus")
    end = datetime.now()
    candidates = list(iter_recent_files(
        [Path(target.inbox).expanduser()], end - timedelta(days=window_days), end,
    ))
    sources = {}
    for source in ("desktop", "android-capture"):
        eligible = _filter_media_candidates_by_source(candidates, source)
        eligible = _select_media_candidates(
            eligible, max_files=len(eligible), android_min_files=0,
        )
        pending, excluded = _filter_processed_media(eligible, corpus)
        count = len(pending)
        level = (
            "critical" if count >= critical_threshold else
            "warning" if count >= warning_threshold else "ok"
        )
        sources[source] = {
            "pending": count, "processed_or_claimed": excluded,
            "severity": level,
            "oldest_pending": min((item.mtime for item in pending), default=None),
        }
        oldest = sources[source]["oldest_pending"]
        sources[source]["oldest_pending"] = oldest.isoformat() if oldest else None
    findings = [
        f"{source}: {row['pending']} pending ({row['severity']}); "
        f"oldest={row['oldest_pending']}"
        for source, row in sources.items() if row["severity"] != "ok"
    ]
    message_ids = []
    if findings and notify:
        message_ids = _notify_telegram(
            f"Pending captures in the last {window_days} days\n"
            + "\n".join(findings)
            + "\nReview analyzer runs and replay missed dates before they age out."
        )
    return {
        "ok": not findings, "window_days": window_days,
        "sources": sources, "telegram_message_ids": message_ids,
        "notification_requested": notify,
    }


@SPROUT.task()
@log_result()
def monitor_pending_captures(
    *, window_days: int = 14, warning_threshold: int = 25,
    critical_threshold: int = 100, notify: bool = True,
) -> dict[str, Any]:
    return _monitor_pending_captures(
        window_days=window_days, warning_threshold=warning_threshold,
        critical_threshold=critical_threshold, notify=notify,
    )
