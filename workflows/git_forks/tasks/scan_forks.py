"""Weekly Git/GitHub fleet scan followed by per-fork HFL persistence."""

from __future__ import annotations

from core.apps.es_logging.app.elasticsearch import log_result
from core.apps.sprout.app.celery import SPROUT
from core.utilities.logging.custom_logger import create_logger

from apps.git.fleet import scan_fleet
from workflows.git_forks.hfl import persist_scan_entries


_log = create_logger("git_forks.scan_forks")


@SPROUT.task()
@log_result()
def scan_fork_fleet() -> dict:
    """Scan every managed fork and write per-instance plus fleet HFL entries."""
    report = scan_fleet()
    report["hfl"] = persist_scan_entries(report)
    _log.info(
        "scan_fork_fleet: %d fork(s), %d error(s), %d HFL entries",
        report["summary"]["total"], report["summary"]["errors"], report["hfl"]["entries"],
    )
    return {
        "summary": report["summary"],
        "report_path": report.get("report_path"),
        "hfl_entries": report["hfl"]["entries"],
    }
