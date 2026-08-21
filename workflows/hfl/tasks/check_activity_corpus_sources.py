"""Weekly deterministic HFL source-health snapshot.

The Celery task collects bounded evidence, writes failure-only review artifacts,
and leaves adaptive diagnosis/remediation to the paired agent skill.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any, Optional

from core.apps.es_logging.app.elasticsearch import log_result
from core.apps.sprout.app.celery import SPROUT
from core.utilities.logging.custom_logger import create_logger

from workflows.hfl.dto import HflEntry
from workflows.hfl.persistence import submit_hfl_entry
from workflows.hfl.source_health import (
    HealthSnapshot,
    render_failure_report,
    scan_activity_corpus_sources,
    write_failure_report,
)


_log = create_logger("hfl.check_activity_corpus_sources")


def _notify_telegram(text: str) -> list[int]:
    from apps.telegram.config import CONFIG as telegram_config
    from apps.telegram.references.web.api.messages import ApiServiceTelegramMessages

    chat_id = telegram_config.app_data.get("default_chat_id")
    if not chat_id:
        raise RuntimeError("Telegram default_chat_id is missing")
    summary = text[:3800]
    response = ApiServiceTelegramMessages(telegram_config).send_message(
        chat_id=chat_id,
        text="HFL source-health failures\n\n" + summary,
    )
    message_id = response.get("message_id") if isinstance(response, dict) else None
    if isinstance(message_id, bool) or not isinstance(message_id, int) or message_id <= 0:
        raise RuntimeError("Telegram response did not contain a valid message_id")
    return [message_id]


def _write_hfl_audit(snapshot: HealthSnapshot, report: str, report_path: Optional[Path]) -> dict[str, Any]:
    finding_count = len(snapshot.failures) + len(snapshot.registry_errors)
    entry = HflEntry(
        when=datetime.fromisoformat(snapshot.generated_at).replace(tzinfo=None),
        moment=f"HFL source-health audit found {finding_count} finding(s)",
        what_happened=report,
        why_it_stayed="Source ingestion or corpus/index parity required operational attention.",
        possible_use="Use the evidence and actions to restore missed activity safely.",
        tags=("hfl", "source-health", "failure", "operations"),
        references=(str(report_path),) if report_path else (),
        source="activity-corpus-source-check",
        synthesized=False,
    )
    return submit_hfl_entry(
        entry,
        source="activity-corpus-source-check",
        synthesized=False,
        dedup_key=snapshot.correlation_id or snapshot.generated_at,
    )


def run_activity_corpus_source_check(
    *,
    mode: str = "weekly",
    write_report: bool = True,
    save_to_hfl: bool = True,
    notify: bool = True,
    dry_run: bool = False,
    now: Optional[datetime] = None,
) -> dict[str, Any]:
    """Collect source health and emit artifacts only when failures exist."""
    if mode not in {"daily", "weekly"}:
        raise ValueError("mode must be daily or weekly")
    snapshot = scan_activity_corpus_sources(mode=mode, now=now)
    failures = snapshot.failures
    if not failures and not snapshot.registry_errors:
        return {
            "status": "healthy",
            "mode": mode,
            "sources_checked": len(snapshot.sources),
            "failure_count": 0,
            "correlation_id": snapshot.correlation_id,
            "report": None,
            "hfl_audit": None,
            "telegram_message_ids": [],
        }

    report_text = render_failure_report(snapshot)
    report_path = None if dry_run or not write_report else write_failure_report(snapshot)
    errors: list[str] = []
    audit = None
    message_ids: list[int] = []
    if save_to_hfl and not dry_run:
        try:
            audit = _write_hfl_audit(snapshot, report_text, report_path)
        except Exception as exc:  # noqa: BLE001 - retain the primary report
            errors.append(f"hfl-audit:{type(exc).__name__}")
            _log.warning("source-health HFL audit failed (%s)", exc)
    if notify and not dry_run:
        try:
            source_lines = [
                f"- {item.key}: {'; '.join(item.reasons)}" for item in failures
            ]
            registry_lines = [f"- registry: {error}" for error in snapshot.registry_errors]
            compact = "\n".join([*source_lines, *registry_lines])
            message_ids = _notify_telegram(compact)
        except Exception as exc:  # noqa: BLE001 - retain the primary report
            errors.append(f"telegram:{type(exc).__name__}")
            _log.warning("source-health Telegram notification failed (%s)", exc)
    status = "partial" if errors else snapshot.status
    return {
        "status": status,
        "mode": mode,
        "sources_checked": len(snapshot.sources),
        "failure_count": len(failures) + len(snapshot.registry_errors),
        "correlation_id": snapshot.correlation_id,
        "failed_sources": [item.key for item in failures],
        "report": str(report_path) if report_path else None,
        "hfl_audit": audit,
        "telegram_message_ids": message_ids,
        "errors": errors,
        "dry_run": dry_run,
    }


@SPROUT.task()
@log_result()
def check_activity_corpus_sources(
    *,
    mode: str = "weekly",
    write_report: bool = True,
    save_to_hfl: bool = True,
    notify: bool = True,
    dry_run: bool = False,
) -> dict[str, Any]:
    """Run the canonical deterministic HFL source-health audit."""
    return run_activity_corpus_source_check(
        mode=mode,
        write_report=write_report,
        save_to_hfl=save_to_hfl,
        notify=notify,
        dry_run=dry_run,
    )
