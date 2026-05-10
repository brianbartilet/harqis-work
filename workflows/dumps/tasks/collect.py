"""
workflows/dumps/tasks/collect.py

Broadcast task — every Celery worker subscribed to `default_broadcast`
collects yesterday's files from its own paths and ships them to harqis-server's
inbox. If the worker IS harqis-server, the ship step degrades to a local copy.
"""
from __future__ import annotations

from pathlib import Path

from core.apps.sprout.app.celery import SPROUT
from core.apps.es_logging.app.elasticsearch import log_result
from core.utilities.logging.custom_logger import create_logger

from workflows.dumps.config import (
    get_dumps_target,
    get_local_dumps_config,
)
from workflows.dumps.files import (
    format_dump_dir_name,
    group_by_source,
    iter_recent_files,
    previous_day_window,
)
from workflows.dumps.transport import copy_locally, ship_via_ssh_tar

_log = create_logger("dumps.collect")


@SPROUT.task(name="workflows.dumps.tasks.broadcast_collect_daily_dumps")
@log_result()
def broadcast_collect_daily_dumps(**kwargs) -> dict:
    """Collect yesterday's files on this worker and ship to harqis-server.

    Returns a dict with `machine`, `files_count`, `bytes_total`, and
    `destination` so the result is greppable in Elasticsearch / Flower.
    """
    local = get_local_dumps_config()
    if not local.paths:
        _log.info("dumps: no [%s.daily_dumps] paths configured — skipping",
                  local.machine_name)
        return {
            "machine": local.machine_name,
            "files_count": 0,
            "destination": None,
            "skipped": "no paths configured",
        }

    start, end = previous_day_window()
    _log.info("dumps: %s scanning %d path(s) for files in [%s, %s)",
              local.machine_name, len(local.paths), start, end)

    files = list(iter_recent_files(local.paths, start, end))
    if not files:
        _log.info("dumps: %s — 0 files matched the previous-day window",
                  local.machine_name)
        return {
            "machine": local.machine_name,
            "files_count": 0,
            "destination": None,
            "skipped": "no recent files",
        }

    bytes_total = sum(f.path.stat().st_size for f in files if f.path.exists())
    machine_dir = format_dump_dir_name(local.machine_name, start)

    # ── Local short-circuit: this worker IS harqis-server. Just copy. ────────
    if local.is_harqis_server:
        target = get_dumps_target()
        if not target:
            _log.error("dumps: harqis-server has no [dumps] inbox configured")
            return {
                "machine": local.machine_name,
                "files_count": len(files),
                "destination": None,
                "error": "harqis_server_inbox not set in [dumps]",
            }
        inbox = Path(target.inbox).expanduser()
        written = copy_locally(files, inbox, machine_dir)
        dest = str(inbox / machine_dir)
        _log.info("dumps: %s wrote %d/%d file(s) locally to %s",
                  local.machine_name, written, len(files), dest)
        return {
            "machine": local.machine_name,
            "files_count": written,
            "bytes_total": bytes_total,
            "destination": dest,
        }

    # ── Remote ship via ssh+tar ──────────────────────────────────────────────
    target = get_dumps_target()
    if not target:
        _log.error("dumps: [dumps] harqis_server_ssh / harqis_server_inbox missing — "
                   "cannot ship from %s", local.machine_name)
        return {
            "machine": local.machine_name,
            "files_count": len(files),
            "destination": None,
            "error": "harqis_server_ssh/inbox not configured",
        }

    # Per-source-root shipping keeps each archive's relative-path layout intact.
    written = 0
    by_source = group_by_source(files)
    for source_root, source_files in by_source.items():
        n = ship_via_ssh_tar(
            source_files,
            ssh_target=target.ssh,
            inbox_root=target.inbox,
            machine_name_dir=machine_dir,
        )
        written += n
        _log.info("dumps: %s shipped %d file(s) from %s -> %s:%s/%s/%s",
                  local.machine_name, n, source_root,
                  target.ssh, target.inbox, machine_dir, source_root.name)

    dest = f"{target.ssh}:{target.inbox}/{machine_dir}"
    return {
        "machine": local.machine_name,
        "files_count": written,
        "bytes_total": bytes_total,
        "destination": dest,
    }
