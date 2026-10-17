"""
workflows/finance/ibkr_ledger.py

IBKR capture: records new Interactive Brokers stock trades and deposits/withdrawals
in local ledgers.

This step talks to IBKR only — it has no Google dependency. The ledger is the
hand-off to the separate Sheets sync step (workflows/finance/sheets_sync.py), so
captures keep working even when Google access is unavailable and the sheet
catches up on its next sync.

Ledger: ${HARQIS_DATA_ROOT}/finance/ibkr_trades.jsonl (default: <repo>/.harqis-data/...),
one JSON object per execution, de-duplicated by IBKR trade ID; deposits/withdrawals go to
ibkr_cash.jsonl next to it, de-duplicated by transaction ID. Both are gitignored.

Kept free of Celery imports so it also runs from scripts/ibkr_trade_log.py.
"""
from __future__ import annotations

import json
import os
from dataclasses import asdict
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Iterable, List, Optional, Set

from core.utilities.logging.custom_logger import create_logger

from apps.apps_config import CONFIG_MANAGER
from apps.ibkr.references.dto.trade import DtoIbkrCashTransaction, DtoIbkrTrade
from apps.ibkr.references.web.api.flex import date_ranges

_log = create_logger("finance.ibkr_ledger")

STOCK_CATEGORY = "STK"
LEDGER_RELATIVE_PATH = Path("finance") / "ibkr_trades.jsonl"
CASH_LEDGER_NAME = "ibkr_cash.jsonl"
DEPOSIT_TYPE = "Deposits/Withdrawals"
DIVIDEND_TYPES = ("Dividends", "Payment In Lieu Of Dividends", "Withholding Tax")
CASH_TYPES = (DEPOSIT_TYPE,) + DIVIDEND_TYPES


def configured(value) -> str:
    """Config values for unset env vars come through as the literal '${VAR}'."""
    value = "" if value is None else str(value).strip()
    return "" if value.startswith("${") else value


def ledger_path() -> Path:
    root = os.environ.get("HARQIS_DATA_ROOT", "").strip()
    base = Path(root).expanduser() if root else Path(__file__).resolve().parents[2] / ".harqis-data"
    return base / LEDGER_RELATIVE_PATH


def cash_ledger_path() -> Path:
    return ledger_path().parent / CASH_LEDGER_NAME


def load_ledger(path: Optional[Path] = None) -> List[dict]:
    path = path or ledger_path()
    if not path.exists():
        return []
    with path.open(encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def resolve_start_date(explicit: Optional[str] = None) -> date:
    raw = explicit or os.environ.get("IBKR_CAPTURE_START_DATE", "")
    if not raw:
        raise ValueError("Set IBKR_CAPTURE_START_DATE=YYYY-MM-DD in .env/apps.env (first day to record).")
    return datetime.strptime(raw.strip(), "%Y-%m-%d").date()


def fill_key(symbol, trade_time, quantity, price) -> tuple:
    """Secondary identity of an execution, for reports that label IDs differently."""
    def number(value):
        try:
            return round(abs(float(value)), 6)
        except (TypeError, ValueError):
            return None
    when = trade_time.strftime("%Y-%m-%d %H:%M:%S") if isinstance(trade_time, datetime) else str(trade_time or "")
    return str(symbol or "").upper(), when, number(quantity), number(price)


def select_new_trades(trades: Iterable[DtoIbkrTrade], existing_ids: Set[str], start: date,
                      existing_keys: Optional[Set[tuple]] = None) -> List[DtoIbkrTrade]:
    """Stocks only, on/after the start date, not already captured (by ID or fill), oldest first."""
    seen_ids, seen_keys = set(existing_ids), set(existing_keys or ())
    selected = []
    for trade in trades:
        if trade.asset_category != STOCK_CATEGORY or not trade.trade_id or trade.trade_id in seen_ids:
            continue
        if trade.trade_date is None or trade.trade_date < start:
            continue
        key = fill_key(trade.symbol, trade.trade_time, trade.quantity, trade.price)
        if key in seen_keys:
            continue
        seen_ids.add(trade.trade_id)
        seen_keys.add(key)
        selected.append(trade)
    return sorted(selected, key=lambda t: t.trade_time)


def to_ledger_entry(trade: DtoIbkrTrade, captured_at: str) -> dict:
    entry = asdict(trade)
    entry["trade_time"] = trade.trade_time.strftime("%Y-%m-%d %H:%M:%S") if trade.trade_time else None
    entry["captured_at"] = captured_at
    return entry


def select_new_cash(transactions: Iterable[DtoIbkrCashTransaction], existing_ids: Set[str],
                    start: date, types: Iterable[str] = CASH_TYPES) -> List[DtoIbkrCashTransaction]:
    """Cash transactions of the given types on/after the start date, not already captured, oldest first."""
    seen, types = set(existing_ids), set(types)
    selected = []
    for txn in transactions:
        if txn.type not in types or not txn.transaction_id or txn.transaction_id in seen:
            continue
        if txn.date is None or txn.date < start:
            continue
        seen.add(txn.transaction_id)
        selected.append(txn)
    return sorted(selected, key=lambda t: t.date_time)


def to_cash_ledger_entry(txn: DtoIbkrCashTransaction, captured_at: str) -> dict:
    entry = asdict(txn)
    entry["date_time"] = txn.date_time.strftime("%Y-%m-%d %H:%M:%S") if txn.date_time else None
    entry["captured_at"] = captured_at
    return entry


def describe_cash(entry: dict) -> str:
    return f"{(entry.get('date_time') or '')[:10]} {entry.get('currency')} {entry.get('amount') or 0:,.2f} ({entry.get('type')})"


def _append(path: Path, entries: List[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        for entry in entries:
            f.write(json.dumps(entry) + "\n")


def describe(entry: dict) -> str:
    return f"{entry.get('trade_time')} {entry.get('side')} {entry.get('quantity') or 0:g} {entry.get('symbol')}"


def capture_trades(cfg_id__ibkr: str = "IBKR", start_date: Optional[str] = None, dry_run: bool = False,
                   path: Optional[Path] = None, cash_path: Optional[Path] = None) -> dict:
    """Fetch IBKR reports; append new stock trades and deposits/withdrawals to the local ledgers."""
    from apps.ibkr.references.web.api.flex import (
        ApiServiceIbkrFlex, parse_cash_transactions, parse_trades,
    )

    start = resolve_start_date(start_date)
    cfg__ibkr = CONFIG_MANAGER.get(cfg_id__ibkr)
    query_ids = [q for q in (configured(cfg__ibkr.app_data.get("flex_query_id_trades")),
                             configured(cfg__ibkr.app_data.get("flex_query_id_activity"))) if q]
    if not configured(cfg__ibkr.app_data.get("flex_token")) or not query_ids:
        raise ValueError("Set IBKR_FLEX_TOKEN and IBKR_FLEX_QUERY_ID_TRADES (and/or "
                         "IBKR_FLEX_QUERY_ID_ACTIVITY) in .env/apps.env.")

    path = path or ledger_path()
    cash_path = cash_path or cash_ledger_path()
    ledger = load_ledger(path)
    existing_ids = {entry.get("trade_id") for entry in ledger}
    existing_keys = {fill_key(e.get("symbol"), e.get("trade_time"), e.get("quantity"), e.get("price")) for e in ledger}
    existing_cash_ids = {entry.get("transaction_id") for entry in load_ledger(cash_path)}

    # ── Step 1: Fetch from IBKR (Trade Confirmation = today, Activity = rolling week) ──
    # One download per query; trades and cash transactions are parsed from the same report.
    service = ApiServiceIbkrFlex(cfg__ibkr)
    trades, cash = [], []
    for query_id in query_ids:
        statement = service.get_statement_for_query(query_id)
        query_trades, query_cash = parse_trades(statement), parse_cash_transactions(statement)
        _log.info("capture_trades: query %s returned %d execution(s), %d cash transaction(s)",
                  query_id, len(query_trades), len(query_cash))
        trades += query_trades
        cash += query_cash

    # ── Step 2: Keep new stock trades and deposits; append to the ledgers ────
    captured_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    entries = [to_ledger_entry(t, captured_at)
               for t in select_new_trades(trades, existing_ids, start, existing_keys)]
    cash_entries = [to_cash_ledger_entry(t, captured_at)
                    for t in select_new_cash(cash, existing_cash_ids, start)]
    if not dry_run:
        if entries:
            _append(path, entries)
        if cash_entries:
            _append(cash_path, cash_entries)
    _log.info("capture_trades: %s %d new trade(s), %d cash transaction(s)",
              "would capture" if dry_run else "captured", len(entries), len(cash_entries))

    return {
        "fetched": len(trades),
        "new": len(entries),
        "dry_run": dry_run,
        "trades": [describe(e) for e in entries],
        "cash_new": len(cash_entries),
        "cash": [describe_cash(e) for e in cash_entries],
    }


def capture_history(from_date: str, to_date: Optional[str] = None, cfg_id__ibkr: str = "IBKR",
                    types: Iterable[str] = DIVIDEND_TYPES, dry_run: bool = False,
                    cash_path: Optional[Path] = None) -> dict:
    """One-off backfill of past cash transactions (default: dividends and withholding tax).

    Uses the Activity query with explicit date ranges (fd/td) in chunks of <= 365 days,
    up to yesterday by default (IBKR only serves processed days). Deposits and trades are
    deliberately left to the regular capture and its start date.
    """
    from apps.ibkr.references.web.api.flex import ApiServiceIbkrFlex, parse_cash_transactions

    cfg__ibkr = CONFIG_MANAGER.get(cfg_id__ibkr)
    query_id = configured(cfg__ibkr.app_data.get("flex_query_id_activity"))
    if not configured(cfg__ibkr.app_data.get("flex_token")) or not query_id:
        raise ValueError("Set IBKR_FLEX_TOKEN and IBKR_FLEX_QUERY_ID_ACTIVITY in .env/apps.env.")

    start = datetime.strptime(from_date, "%Y-%m-%d").date()
    end = datetime.strptime(to_date, "%Y-%m-%d").date() if to_date else date.today() - timedelta(days=1)
    cash_path = cash_path or cash_ledger_path()
    existing = {entry.get("transaction_id") for entry in load_ledger(cash_path)}

    service = ApiServiceIbkrFlex(cfg__ibkr)
    cash = []
    for fd, td in date_ranges(start, end):
        statement = service.get_statement_for_query(query_id, from_date=fd, to_date=td)
        chunk = parse_cash_transactions(statement)
        _log.info("capture_history: %s-%s returned %d cash transaction(s)", fd, td, len(chunk))
        cash += chunk

    captured_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    entries = [to_cash_ledger_entry(t, captured_at) for t in select_new_cash(cash, existing, start, types)]
    if entries and not dry_run:
        _append(cash_path, entries)
    _log.info("capture_history: %s %d cash transaction(s)", "would capture" if dry_run else "captured", len(entries))
    return {
        "fetched": len(cash),
        "new": len(entries),
        "dry_run": dry_run,
        "trades": [describe_cash(e) for e in entries],
    }
