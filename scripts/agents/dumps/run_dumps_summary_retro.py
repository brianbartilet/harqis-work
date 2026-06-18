#!/usr/bin/env python
"""Retro-summarize one or more days of daily dumps to the HUD feed.

A hands-on companion to the nightly `analyze_daily_dumps` task (which only ever
sees yesterday). Use it to back-fill a summary for a date RANGE, a whole MONTH,
or a single DAY — useful when daily runs were missed (host offline, broker
outage, the host-queue race, etc.). It walks the inbox's existing
`<machine>-daily-dumps-<date>` folders and pushes a per-day breakdown + grand
total to the HUD feed; missed days render as "0 machines (no dumps)".

⚠️  Run this ON harqis-server (the dumps host). The inbox is a LOCAL path there
(`[dumps] harqis_server_inbox`, e.g. /Volumes/harqis-data/dumps). The task
self-guards to harqis-server, so running it elsewhere is a no-op (exit 2).

Usage:
    python scripts/agents/dumps/run_dumps_summary_retro.py                       # yesterday (same as nightly)
    python scripts/agents/dumps/run_dumps_summary_retro.py --days 7              # last 7 full days
    python scripts/agents/dumps/run_dumps_summary_retro.py --date 2026-06-12     # one specific day
    python scripts/agents/dumps/run_dumps_summary_retro.py --start 2026-05-01 --end 2026-05-31
    python scripts/agents/dumps/run_dumps_summary_retro.py --month 2026-05       # whole calendar month
    python scripts/agents/dumps/run_dumps_summary_retro.py --days 30 --missing-only  # only the gaps

Flags (map 1:1 to the task kwargs; precedence: date → start/end → month → days):
    --days N          last N full days ending yesterday
    --date YYYY-MM-DD one specific day (not capped at yesterday)
    --start/--end     inclusive YYYY-MM-DD window (capped at yesterday)
    --month YYYY-MM   whole calendar month (capped at yesterday)
    --missing-only    report only the days with NO dumps (gap report)

Exit codes: 0 ok · 1 error (e.g. inbox/config) · 2 skipped (ran off the hub).
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from dotenv import load_dotenv

# scripts/agents/dumps/run_dumps_summary_retro.py → repo root is parents[3]. Mirror
# pull_dumps.py's bootstrap so `workflows.*`/`apps.*` imports + config resolution
# work whether run via deploy.py or directly from a shell.
REPO_ROOT = Path(__file__).resolve().parents[3]
load_dotenv(REPO_ROOT / ".env" / "apps.env")
import os  # noqa: E402  (after load_dotenv so APP_CONFIG_FILE can be defaulted)

os.environ.setdefault("APP_CONFIG_FILE", "apps_config.yaml")
# Importing the analyze task pulls in the SPROUT celery app, whose package
# __init__ resolves WORKFLOW_CONFIG at import time — set it like launch.py does.
os.environ.setdefault("WORKFLOW_CONFIG", "workflows.config")
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Retro-summarize daily dumps for a range/month/day to the HUD feed.")
    p.add_argument("--days", type=int, help="Last N full days ending yesterday.")
    p.add_argument("--date", help='One specific day "YYYY-MM-DD".')
    p.add_argument("--start", help='Inclusive lower bound "YYYY-MM-DD".')
    p.add_argument("--end", help='Inclusive upper bound "YYYY-MM-DD" (default yesterday).')
    p.add_argument("--month", help='Whole calendar month "YYYY-MM".')
    p.add_argument("--missing-only", action="store_true", dest="missing_only",
                   help="Report only the days with NO dumps (gap report) instead "
                        "of the full per-day breakdown.")
    return p.parse_args()


def main() -> int:
    args = _parse_args()

    from workflows.dumps.tasks.analyze import analyze_daily_dumps

    # Only forward the kwargs the user actually set, so the task's own
    # precedence + "yesterday" default apply unchanged.
    kwargs = {k: v for k, v in (
        ("days", args.days),
        ("date", args.date),
        ("start", args.start),
        ("end", args.end),
        ("month", args.month),
    ) if v is not None}
    if args.missing_only:
        kwargs["missing_only"] = True

    result = analyze_daily_dumps(**kwargs)

    if result.get("error"):
        print(f"ERROR: {result['error']}", file=sys.stderr)
        return 1
    if result.get("skipped"):
        print(f"Skipped: not harqis-server (ran on {result.get('machine')!r}). "
              "Run this on the dumps host.", file=sys.stderr)
        return 2

    # The task's rendered summary is the same text it pushed to the HUD feed.
    print(result.get("text", "").rstrip())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
