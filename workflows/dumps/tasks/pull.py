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
import re

from core.apps.sprout.app.celery import SPROUT
from core.apps.es_logging.app.elasticsearch import log_result
from core.utilities.logging.custom_logger import create_logger

from workflows.dumps.config import get_dumps_target, get_pull_targets
from workflows.dumps.files import format_dump_dir_name, previous_day_window
from workflows.dumps.transport import list_remote_recent_files, pull_via_ssh_tar

_log = create_logger("dumps.pull")


def _redact_ssh_user(text: str) -> str:
    """Redact SSH usernames in operator-facing notifications."""
    return re.sub(r"\b[^\s/@]+@([^\s:]+)", r"<user>@\1", text)


def _send_pull_failure_notification(failures: list[dict], start_iso: str, end_iso: str) -> dict:
    """Send a best-effort Telegram alert when a remote dump pull fails."""
    if not failures:
        return {"sent": False, "skipped": "no failures"}

    lines = [
        "🔴 HARQIS Android dump sync failed",
        f"Window: {start_iso} → {end_iso}",
        "",
    ]
    for failure in failures[:5]:
        device = failure.get("device", "unknown-device")
        stage = failure.get("stage", "unknown-stage")
        source = failure.get("source_root")
        detail = _redact_ssh_user(str(failure.get("error", "unknown error")))
        lines.append(f"- {device}: {stage}" + (f" ({source})" if source else ""))
        lines.append(f"  {detail[:500]}")
    if len(failures) > 5:
        lines.append(f"- … {len(failures) - 5} more failure(s)")
    lines.append("")
    lines.append("Likely check: Termux sshd + Tailscale on the phone, then rerun the pull.")

    try:
        from apps.telegram.config import CONFIG as TELEGRAM_CONFIG
        from apps.telegram.references.web.api.messages import ApiServiceTelegramMessages

        chat_id = TELEGRAM_CONFIG.app_data.get("default_chat_id")
        if not chat_id:
            return {"sent": False, "error": "telegram default_chat_id missing"}
        result = ApiServiceTelegramMessages(TELEGRAM_CONFIG).send_message(
            chat_id=chat_id,
            text="\n".join(lines),
        )
        return {
            "sent": True,
            "message_id": result.get("message_id") if isinstance(result, dict) else None,
        }
    except Exception as exc:  # notification failure must not hide the dump failure
        _log.error("dumps: Telegram failure notification failed: %s", exc)
        return {"sent": False, "error": str(exc)[:500]}


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
    failures: list[dict] = []
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
            failure = {"device": device.name, "stage": "list", "error": str(e)}
            failures.append(failure)
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
                failures.append({
                    "device": device.name,
                    "stage": "pull",
                    "source_root": source_root,
                    "error": str(e),
                })

        summary["devices"].append({"name": device.name, "files_count": device_count})
        summary["pulled_devices"] += 1
        summary["files_count"] += device_count

    if failures:
        summary["failures"] = failures
        summary["notification"] = _send_pull_failure_notification(failures, start_iso, end_iso)

    _log.info("dumps: pull complete — %d device(s), %d file(s) total",
              summary["pulled_devices"], summary["files_count"])
    return summary
