"""
workflows/dumps/tasks/pull.py

Host-side task — runs ON harqis-server. For every device under
[dumps.pull_targets.*] in machines.toml(.local) (typically Android via Termux
SSHD), SSH in, list yesterday's files via `find -newermt`, then stream them
back via `ssh + tar -cf -` and extract into the same inbox the broadcast task
writes to.

The scheduled `pull_daily_dumps_from_remotes` covers the previous day. For
backfills and ad-hoc syncs there is `pull_dumps_manual` (see also
`scripts/pull_dumps.py`), which pulls a date RANGE (one daily-dumps folder per
day, identical layout to the nightly job) or does a FULL sweep of every file on
the device. Both share the same list→tar→extract core, so a manual pull is
indistinguishable from a nightly one to everything downstream (analyze_media,
the memory MCP, …).
"""
from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path
from typing import Callable, Optional
import re

from core.apps.sprout.app.celery import SPROUT
from core.apps.es_logging.app.elasticsearch import log_result
from core.utilities.logging.custom_logger import create_logger

from workflows.dumps.config import PullTarget, get_dumps_target, get_pull_targets
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


def _pull_devices_window(
    pull_targets: list[PullTarget],
    inbox: Path,
    *,
    start: Optional[datetime],
    end: Optional[datetime],
    dir_namer: Callable[[PullTarget], str],
    dry_run: bool = False,
) -> tuple[dict, list[dict]]:
    """List + pull one window for every device. The shared core behind both the
    nightly task and the manual backfill.

    `start`/`end` are naive local datetimes; pass both as ``None`` for a full
    sweep (every file). `dir_namer` maps a device to its destination folder
    under `inbox`. With `dry_run` the remote listing still runs (so counts are
    real) but nothing is transferred. Returns ``(summary, failures)``.
    """
    start_iso = start.strftime("%Y-%m-%d %H:%M:%S") if start else None
    end_iso = end.strftime("%Y-%m-%d %H:%M:%S") if end else None

    summary: dict = {"pulled_devices": 0, "files_count": 0, "devices": []}
    failures: list[dict] = []
    for device in pull_targets:
        machine_dir = dir_namer(device)
        _log.info("dumps: %s from %s (%s) into %s/%s",
                  "listing" if dry_run else "pulling",
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
            failures.append({"device": device.name, "stage": "list", "error": str(e)})
            summary["devices"].append({
                "name": device.name, "files_count": 0, "error": str(e),
            })
            continue

        device_count = 0
        for source_root, files in listing.items():
            if dry_run:
                device_count += len(files)
                continue
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

        summary["devices"].append({
            "name": device.name, "files_count": device_count, "dir": machine_dir,
        })
        summary["pulled_devices"] += 1
        summary["files_count"] += device_count

    return summary, failures


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
    summary, failures = _pull_devices_window(
        pull_targets, inbox, start=start, end=end,
        dir_namer=lambda d: format_dump_dir_name(d.name, start),
    )

    if failures:
        summary["failures"] = failures
        summary["notification"] = _send_pull_failure_notification(
            failures,
            start.strftime("%Y-%m-%d %H:%M:%S"),
            end.strftime("%Y-%m-%d %H:%M:%S"),
        )

    _log.info("dumps: pull complete — %d device(s), %d file(s) total",
              summary["pulled_devices"], summary["files_count"])
    return summary


# ── Manual backfill / full sweep ──────────────────────────────────────────────

def resolve_manual_window(
    *,
    since: Optional[str] = None,
    until: Optional[str] = None,
    days: Optional[int] = None,
    now: Optional[datetime] = None,
) -> tuple[datetime, datetime]:
    """Resolve a manual pull window to date-aligned ``[start, end)`` midnights
    (``end`` exclusive, so ``until`` is an INCLUSIVE calendar day).

    Precedence: explicit ``since``/``until`` → ``days`` (last N days incl. today)
    → default (yesterday only, matching the nightly job). ``since``/``until``
    accept ``YYYY-MM-DD`` (or any ISO date).
    """
    now = now or datetime.now()
    today = datetime(now.year, now.month, now.day)

    if since:
        s = datetime.fromisoformat(since)
        start = datetime(s.year, s.month, s.day)
    elif days:
        start = today - timedelta(days=max(1, int(days)) - 1)
    else:
        start = today - timedelta(days=1)

    if until:
        u = datetime.fromisoformat(until)
        end = datetime(u.year, u.month, u.day) + timedelta(days=1)
    elif since or days:
        end = today + timedelta(days=1)   # through today, inclusive
    else:
        end = today                        # yesterday-only window

    if end <= start:
        end = start + timedelta(days=1)
    return start, end


def pull_dumps_manual(
    *,
    since: Optional[str] = None,
    until: Optional[str] = None,
    days: Optional[int] = None,
    full: bool = False,
    per_day: bool = True,
    device: Optional[str] = None,
    dry_run: bool = False,
    notify: bool = False,
    now: Optional[datetime] = None,
) -> dict:
    """Ad-hoc pull from [dumps.pull_targets.*] devices — backfill or full sweep.

    Runs ON harqis-server (the inbox is a local path there). Best-effort: never
    raises; per-device failures are collected into the result.

    Modes:
      * ``full=True``     — every file on the device → ONE folder per device,
        ``<device>-full-dumps-YYYY-MM-DD`` (today's date). No date split (the
        remote ``find`` stays portable — no ``-printf`` — so we don't read
        per-file mtimes for bucketing).
      * range + ``per_day`` (default) — one ``find``/``tar`` cycle per calendar
        day, each into ``<device>-daily-dumps-YYYY-MM-DD`` — byte-identical
        layout to the nightly job, so a range pull backfills the inbox exactly
        as if the job had run each night.
      * range + ``per_day=False`` — the whole range in ONE folder per device,
        ``<device>-range-dumps-<from>_<to>`` (one SSH cycle, no per-day split).

    Args:
        since/until: ``YYYY-MM-DD`` window bounds (``until`` inclusive).
        days:        last N days including today (ignored if ``since`` given).
        full:        sweep every file (ignores since/until/days).
        per_day:     range layout — daily folders (True) vs one folder (False).
        device:      limit to a single pull-target by name.
        dry_run:     list only — report counts, transfer nothing.
        notify:      send the Telegram failure alert on errors (off by default
                     for manual runs — the operator sees the result directly).
    """
    target = get_dumps_target()
    if not target:
        return {"pulled_devices": 0, "error": "harqis_server_inbox not set"}

    pull_targets = get_pull_targets()
    if device:
        pull_targets = [t for t in pull_targets if t.name == device]
        if not pull_targets:
            return {"pulled_devices": 0, "error": f"no pull target named {device!r}"}
    if not pull_targets:
        return {"pulled_devices": 0, "skipped": "no pull targets configured"}

    inbox = Path(target.inbox).expanduser()
    now = now or datetime.now()
    failures: list[dict] = []

    if full:
        run_day = now.strftime("%Y-%m-%d")
        summary, failures = _pull_devices_window(
            pull_targets, inbox, start=None, end=None,
            dir_namer=lambda d: f"{d.name}-full-dumps-{run_day}",
            dry_run=dry_run,
        )
        summary["mode"] = "full"
    else:
        start, end = resolve_manual_window(since=since, until=until, days=days, now=now)
        if per_day:
            summary = {"pulled_devices": 0, "files_count": 0, "devices": [], "days": []}
            per_device: dict[str, int] = {}
            day = start
            while day < end:
                next_day = day + timedelta(days=1)
                day_summary, day_failures = _pull_devices_window(
                    pull_targets, inbox, start=day, end=next_day,
                    dir_namer=lambda d, _day=day: format_dump_dir_name(d.name, _day),
                    dry_run=dry_run,
                )
                failures.extend(day_failures)
                summary["files_count"] += day_summary["files_count"]
                summary["days"].append({
                    "day": day.strftime("%Y-%m-%d"),
                    "files_count": day_summary["files_count"],
                })
                for dev in day_summary["devices"]:
                    per_device[dev["name"]] = per_device.get(dev["name"], 0) + dev["files_count"]
                day = next_day
            summary["devices"] = [{"name": k, "files_count": v} for k, v in per_device.items()]
            summary["pulled_devices"] = len(per_device)
            summary["mode"] = "range-per-day"
        else:
            label = f"{start.strftime('%Y-%m-%d')}_{(end - timedelta(days=1)).strftime('%Y-%m-%d')}"
            summary, failures = _pull_devices_window(
                pull_targets, inbox, start=start, end=end,
                dir_namer=lambda d: f"{d.name}-range-dumps-{label}",
                dry_run=dry_run,
            )
            summary["mode"] = "range-single"
        summary["window"] = {
            "start": start.strftime("%Y-%m-%d"),
            "end_exclusive": end.strftime("%Y-%m-%d"),
        }

    summary["dry_run"] = dry_run
    if failures:
        summary["failures"] = failures
        if notify and not dry_run:
            summary["notification"] = _send_pull_failure_notification(
                failures, summary.get("mode", "manual"), "")

    _log.info("dumps: manual pull (%s%s) — %d device(s), %d file(s)",
              summary.get("mode"), " dry-run" if dry_run else "",
              summary["pulled_devices"], summary["files_count"])
    return summary
