"""Capture IBKR stock trades to a local ledger and publish them to a Google Sheet.

Standalone runner for machines without the Celery stack (e.g. Windows Task
Scheduler every 30 minutes). Same logic as the Celery tasks
`workflows.finance.tasks.ibkr_trades.capture_ibkr_trades` and
`workflows.finance.tasks.trade_log_sheet.sync_trade_log_sheet`.

The two operations are independent: `capture` only talks to IBKR, `sync` only
talks to Google. `run` does both, and still syncs if the capture fails.

Usage (from the repo root, venv python):
    python scripts/ibkr_trade_log.py create-sheet           # new sheet from the template
    python scripts/ibkr_trade_log.py prepare-sheet [--dry-run]  # add missing headers to an existing sheet
    python scripts/ibkr_trade_log.py capture [--dry-run]
    python scripts/ibkr_trade_log.py sync [--dry-run]
    python scripts/ibkr_trade_log.py run [--dry-run]        # capture, then sync
    python scripts/ibkr_trade_log.py capture-history --from 2025-01-01 [--dry-run]
                                                            # one-off: past dividends/withholding tax

Each run appends one line per operation to logs/ibkr_trade_log.log.
"""

from __future__ import annotations

import argparse
import os
import sys
from datetime import datetime
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]


def _summary(name: str, result: dict) -> str:
    verb = "would add" if result["dry_run"] else "added"
    source = f"fetched {result['fetched']}" if "fetched" in result else f"ledger {result['ledger']}"
    lines = [f"{name}: {source}, {verb} {result['new']}"]
    lines += [f"  {line}" for line in result["trades"]]
    for tab in result.get("tabs", []):
        if tab["already_recorded_by_hand"]:
            lines.append(f"  [{tab['tab']}] skipped {tab['already_recorded_by_hand']} already entered by hand")
        for added in tab.get("summary_added", []):
            lines.append(f"  [{tab['tab']}] summary {'row would be added' if result['dry_run'] else 'row added'} - {added}")
        if tab["new_symbols"]:
            lines.append(f"  [{tab['tab']}] new symbol(s) - add to the summary tab: {', '.join(tab['new_symbols'])}")
    lines += [f"  not routed to any tab: {line}" for line in result.get("unrouted", [])]
    if "cash_new" in result:
        lines.append(f"  deposits/withdrawals: {verb} {result['cash_new']}")
        lines += [f"    {line}" for line in result["cash"]]
    deposits = result.get("deposits")
    if deposits:
        lines.append(f"  deposits: ledger {deposits['ledger']}, {verb} {deposits['new']}")
        lines += [f"    {line}" for line in deposits["lines"]]
        if deposits["already_recorded_by_hand"]:
            lines.append(f"    skipped {deposits['already_recorded_by_hand']} already entered by hand")
        lines += [f"    not written (currency filter): {line}" for line in deposits["unmatched"]]
    dividends = result.get("dividends")
    if dividends and (dividends["new"] or dividends["created_tab"]):
        created = f" (creates tab '{dividends['tab']}')" if dividends["created_tab"] else ""
        lines.append(f"  dividends: {verb} {dividends['new']}{created}")
        lines += [f"    {line}" for line in dividends["lines"]]
    return "\n".join(lines)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("operation",
                        choices=["create-sheet", "prepare-sheet", "capture", "sync", "run", "capture-history"])
    parser.add_argument("--from", dest="from_date", help="capture-history: first day (YYYY-MM-DD)")
    parser.add_argument("--to", dest="to_date", help="capture-history: last day (default: yesterday)")
    parser.add_argument("--dry-run", action="store_true", help="show what would change, write nothing")
    args = parser.parse_args(argv)

    os.chdir(REPO_ROOT)
    sys.path.insert(0, str(REPO_ROOT))
    from dotenv import load_dotenv
    load_dotenv(REPO_ROOT / ".env" / "apps.env")

    steps = []
    if args.operation == "create-sheet":
        from workflows.finance.sheets_sync import create_sheet
        steps.append(("create-sheet", lambda: create_sheet()))
    elif args.operation == "capture-history":
        if not args.from_date:
            parser.error("capture-history needs --from YYYY-MM-DD")
        from workflows.finance.ibkr_ledger import capture_history
        steps.append(("capture-history",
                      lambda: capture_history(args.from_date, args.to_date, dry_run=args.dry_run)))
    elif args.operation == "prepare-sheet":
        from workflows.finance.sheets_sync import prepare_sheet
        steps.append(("prepare-sheet", lambda: prepare_sheet(dry_run=args.dry_run)))
    else:
        if args.operation in ("capture", "run"):
            from workflows.finance.ibkr_ledger import capture_trades
            steps.append(("capture", lambda: capture_trades(dry_run=args.dry_run)))
        if args.operation in ("sync", "run"):
            from workflows.finance.sheets_sync import sync_to_sheet
            steps.append(("sync", lambda: sync_to_sheet(dry_run=args.dry_run)))

    code = 0
    lines = []
    for name, step in steps:
        try:
            result = step()
            if name == "create-sheet":
                lines.append(f"create-sheet: https://docs.google.com/spreadsheets/d/{result} "
                             f"- set TRADE_LOG_SHEET_ID={result} in .env/apps.env")
            elif name == "prepare-sheet":
                verb = "would add" if args.dry_run else "added"
                lines.append(f"prepare-sheet: {verb} {len(result)} header(s)" + "".join(f"\n  {c}" for c in result))
            else:
                lines.append(_summary(name, result))
        except Exception as e:
            lines.append(f"{name}: FAILED - {type(e).__name__}: {e}")
            code = 1

    message = "\n".join(lines)
    print(message)
    log_path = REPO_ROOT / "logs" / "ibkr_trade_log.log"
    log_path.parent.mkdir(exist_ok=True)
    with log_path.open("a", encoding="utf-8") as log:
        log.write(f"{datetime.now():%Y-%m-%d %H:%M:%S} {message}\n")
    return code


if __name__ == "__main__":
    raise SystemExit(main())
