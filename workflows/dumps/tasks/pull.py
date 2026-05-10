"""
workflows/dumps/tasks/pull.py

Host-side task — runs ON harqis-server. For every device under
[dumps.pull_targets.*] in machines.toml(.local) (typically Android via Termux
SSHD), SSH in, list yesterday's files via `find -newermt`, then stream them
back via `ssh + tar -cf -` and extract into the same inbox the broadcast task
writes to.
"""
from __future__ import annotations

from pathlib import Path

from core.apps.sprout.app.celery import SPROUT
from core.apps.es_logging.app.elasticsearch import log_result
from core.utilities.logging.custom_logger import create_logger

from workflows.dumps.config import get_dumps_target, get_pull_targets
from workflows.dumps.files import format_dump_dir_name, previous_day_window
from workflows.dumps.transport import list_remote_recent_files, pull_via_ssh_tar

_log = create_logger("dumps.pull")


@SPROUT.task(name="workflows.dumps.tasks.pull_daily_dumps_from_remotes")
@log_result()
def pull_daily_dumps_from_remotes(**kwargs) -> dict:
    """Pull yesterday's files from every [dumps.pull_targets.*] device."""
    target = get_dumps_target()
    if not target:
        _log.error("dumps: [dumps] harqis_server_inbox missing — cannot pull")
        return {"pulled_devices": 0, "error": "harqis_server_inbox not set"}

    pull_targets = get_pull_targets()
    if not pull_targets:
        _log.info("dumps: no [dumps.pull_targets.*] entries — nothing to pull")
        return {"pulled_devices": 0, "skipped": "no pull targets configured"}

    inbox = Path(target.inbox).expanduser()
    start, end = previous_day_window()
    start_iso = start.strftime("%Y-%m-%d %H:%M:%S")
    end_iso = end.strftime("%Y-%m-%d %H:%M:%S")

    summary = {"pulled_devices": 0, "files_count": 0, "devices": []}
    for device in pull_targets:
        machine_dir = format_dump_dir_name(device.name, start)
        _log.info("dumps: pulling from %s (%s) into %s/%s",
                  device.name, device.ssh, inbox, machine_dir)
        try:
            listing = list_remote_recent_files(
                ssh_target=device.ssh,
                paths=device.paths,
                start_iso=start_iso,
                end_iso=end_iso,
                ssh_port=device.port,
            )
        except RuntimeError as e:
            _log.error("dumps: list failed on %s: %s", device.name, e)
            summary["devices"].append({
                "name": device.name, "files_count": 0, "error": str(e),
            })
            continue

        device_count = 0
        for source_root, files in listing.items():
            try:
                n = pull_via_ssh_tar(
                    ssh_target=device.ssh,
                    source_root=source_root,
                    files=files,
                    local_inbox=inbox,
                    machine_name_dir=machine_dir,
                    ssh_port=device.port,
                )
                device_count += n
                _log.info("dumps: %s pulled %d/%d files from %s",
                          device.name, n, len(files), source_root)
            except RuntimeError as e:
                _log.error("dumps: pull failed on %s:%s: %s",
                           device.name, source_root, e)

        summary["devices"].append({"name": device.name, "files_count": device_count})
        summary["pulled_devices"] += 1
        summary["files_count"] += device_count

    _log.info("dumps: pull complete — %d device(s), %d file(s) total",
              summary["pulled_devices"], summary["files_count"])
    return summary
