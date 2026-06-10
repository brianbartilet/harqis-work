#!/usr/bin/env python
"""Manually pull Android (and other) dumps from [dumps.pull_targets.*] devices.

A hands-on companion to the nightly `pull_daily_dumps_from_remotes` task: sync a
DATE RANGE (back-filling one daily-dumps folder per day, identical layout to the
nightly job) or do a FULL sweep of every file on the device. Same
list→ssh+tar→extract path, so what lands in the inbox is indistinguishable from a
nightly pull and flows straight into analyze_hfl_media / the memory MCP.

⚠️  Run this ON harqis-server (the dumps host). The inbox is a LOCAL path there
(`[dumps] harqis_server_inbox`), so running it elsewhere would extract into a
local folder on the wrong machine.

Usage:
    python scripts/pull_dumps.py                      # yesterday (same as nightly)
    python scripts/pull_dumps.py --days 7             # last 7 days, one folder/day
    python scripts/pull_dumps.py --since 2026-05-01 --until 2026-05-31
    python scripts/pull_dumps.py --full               # EVERY file, one folder
    python scripts/pull_dumps.py --days 30 --single-folder
    python scripts/pull_dumps.py --device pixel-7 --dry-run --days 3

Flags:
    --days N          last N days including today (ignored if --since given)
    --since/--until   YYYY-MM-DD window (until inclusive)
    --full            sweep all files (ignores the window); one folder per device
    --single-folder   range → one folder per device instead of one per day
    --device NAME     limit to a single pull-target
    --dry-run         list + count only; transfer nothing
    --notify          send the Telegram failure alert on errors

Exit codes: 0 ok (or dry-run) · 1 a device errored · 2 nothing configured.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from dotenv import load_dotenv

# scripts/pull_dumps.py → repo root is parents[1]. Mirror mcp/server.py's
# bootstrap so `workflows.*`/`apps.*` imports + config resolution work whether
# run via deploy.py or directly from a shell.
REPO_ROOT = Path(__file__).resolve().parents[1]
load_dotenv(REPO_ROOT / ".env" / "apps.env")
import os  # noqa: E402  (after load_dotenv so APP_CONFIG_FILE can be defaulted)

os.environ.setdefault("APP_CONFIG_FILE", "apps_config.yaml")
# Importing the pull task pulls in the SPROUT celery app, whose package __init__
# resolves WORKFLOW_CONFIG at import time — set it like scripts/launch.py does.
os.environ.setdefault("WORKFLOW_CONFIG", "workflows.config")
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Manually pull device dumps (range or full sweep).")
    p.add_argument("--days", type=int, help="Last N days including today.")
    p.add_argument("--since", help='Inclusive lower bound "YYYY-MM-DD".')
    p.add_argument("--until", help='Inclusive upper bound "YYYY-MM-DD" (default today).')
    p.add_argument("--full", action="store_true",
                   help="Sweep EVERY file on the device (ignores the window).")
    p.add_argument("--single-folder", action="store_true",
                   help="Range → one folder per device instead of one per day.")
    p.add_argument("--device", help="Limit to a single [dumps.pull_targets.<name>].")
    p.add_argument("--dry-run", action="store_true", help="List + count only; pull nothing.")
    p.add_argument("--notify", action="store_true", help="Send Telegram alert on failures.")
    return p.parse_args()


def main() -> int:
    args = _parse_args()

    from workflows.dumps.tasks.pull import pull_dumps_manual

    result = pull_dumps_manual(
        since=args.since,
        until=args.until,
        days=args.days,
        full=args.full,
        per_day=not args.single_folder,
        device=args.device,
        dry_run=args.dry_run,
        notify=args.notify,
    )

    if result.get("error"):
        print(f"ERROR: {result['error']}", file=sys.stderr)
        return 2 if "configured" in result["error"] or "inbox" in result["error"] else 1
    if result.get("skipped"):
        print(f"Nothing to do: {result['skipped']}", file=sys.stderr)
        return 2

    mode = result.get("mode", "?")
    window = result.get("window")
    scope = (f"{window['start']}..{window['end_exclusive']} (end excl.)"
             if window else "all files")
    verb = "Would pull" if result.get("dry_run") else "Pulled"
    print(f"Mode: {mode}  Scope: {scope}")
    print(f"{verb} {result['files_count']} file(s) across {result['pulled_devices']} device(s).")

    for dev in result.get("devices", []):
        line = f"  - {dev['name']}: {dev['files_count']} file(s)"
        if dev.get("dir"):
            line += f"  → {dev['dir']}/"
        if dev.get("error"):
            line += f"  ERROR: {dev['error']}"
        print(line)

    days = result.get("days")
    if days:
        nonempty = [d for d in days if d["files_count"]]
        print(f"  ({len(days)} day folder(s); {len(nonempty)} with files)")

    failures = result.get("failures")
    if failures:
        print(f"\n{len(failures)} failure(s):", file=sys.stderr)
        for f in failures[:10]:
            print(f"  - {f.get('device')}: {f.get('stage')} — {f.get('error','')[:200]}",
                  file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
