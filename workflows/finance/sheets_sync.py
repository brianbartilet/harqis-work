"""
workflows/finance/sheets_sync.py

Sheets sync: appends trades from the local IBKR ledger to a Google Sheet.

This step talks to Google only — it never calls IBKR. It reads the ledger written
by the capture step (workflows/finance/ibkr_ledger.py), compares it with what the
sheet already holds, and appends the missing rows.

The sheet layout comes from a template (YAML). Lookup order:
  1. an explicit path, 2. $TRADE_LOG_TEMPLATE_YAML (the YAML itself), 3. $TRADE_LOG_TEMPLATE (a path),
  4. ${HARQIS_DATA_ROOT}/finance/trade_log_sheet.yaml (personal, gitignored),
  5. templates/trade_log_sheet.yaml (the generic default shipped with the repo).

A template has one or more routes; each record goes to the first route whose
`match` fits (e.g. by currency/exchange), and each route names a tab and maps
the tab's row-1 headers to record fields. Columns are matched by header text, so
an existing sheet works as long as its headers are mapped; unmapped headers stay
blank and side-by-side blocks to the right of the mapped columns are untouched.

Kept free of Celery imports so it also runs from scripts/ibkr_trade_log.py.
"""
from __future__ import annotations

import os
import re
from collections import OrderedDict
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

import yaml

from core.utilities.logging.custom_logger import create_logger

from apps.apps_config import CONFIG_MANAGER
from workflows.finance.ibkr_ledger import (
    DEPOSIT_TYPE, cash_ledger_path, configured, describe, describe_cash, ledger_path, load_ledger,
)

_log = create_logger("finance.sheets_sync")

DEFAULT_TEMPLATE = Path(__file__).resolve().parent / "templates" / "trade_log_sheet.yaml"
PERSONAL_TEMPLATE_NAME = "trade_log_sheet.yaml"


# ── Template ──────────────────────────────────────────────────────────────────

def template_path(explicit: Optional[Path] = None) -> Path:
    if explicit:
        return Path(explicit)
    if os.environ.get("TRADE_LOG_TEMPLATE", "").strip():
        return Path(os.environ["TRADE_LOG_TEMPLATE"].strip()).expanduser()
    personal = ledger_path().parent / PERSONAL_TEMPLATE_NAME
    return personal if personal.exists() else DEFAULT_TEMPLATE


def load_template(path: Optional[Path] = None) -> dict:
    inline = os.environ.get("TRADE_LOG_TEMPLATE_YAML", "").strip()
    if inline and not path:
        template = yaml.safe_load(inline)  # e.g. a cloud runner's secret, instead of a local file
    else:
        with template_path(path).open(encoding="utf-8") as f:
            template = yaml.safe_load(f)
    template.setdefault("group_by", "execution")
    template.setdefault("id_field", "record_id")
    for route in template["routes"]:
        if route.get("summary") and not {"tab", "symbol_column"} <= set(route["summary"]):
            raise ValueError(f"Route '{route['tab']}': summary needs tab and symbol_column.")
        route.setdefault("match", {})
        route.setdefault("symbol_prefix", "")
        id_headers = [c["header"] for c in route["columns"] if c.get("field") == template["id_field"]]
        if not id_headers:
            raise ValueError(f"Route '{route['tab']}' has no column for id_field '{template['id_field']}'.")
        route["id_header"] = id_headers[0]
    deposits = template.get("deposits")
    if deposits:
        deposits.setdefault("match", {})
        deposits.setdefault("insert_above_blank_row", False)
        if not any(c.get("field") == "record_id" and "header" in c for c in deposits["columns"]):
            raise ValueError("The deposits section needs a {header: ..., field: record_id} column.")
    dividends = template.get("dividends")
    if dividends and not any(c.get("field") == "record_id" for c in dividends["columns"]):
        raise ValueError("The dividends section needs a {header: ..., field: record_id} column.")
    return template


# ── Records (ledger entries → what one sheet row describes) ───────────────────

def _signed(quantity, side) -> float:
    quantity = abs(float(quantity or 0))
    return -quantity if str(side or "").upper() == "SELL" else quantity


def group_entries(entries: List[dict], group_by: str) -> List[dict]:
    """One record per execution, or per IBKR order (fills combined, price volume-weighted)."""
    if group_by != "order":
        return [dict(e, record_id=e.get("trade_id")) for e in entries]

    groups: "OrderedDict[str, List[dict]]" = OrderedDict()
    for entry in entries:
        groups.setdefault(entry.get("order_id") or entry.get("trade_id"), []).append(entry)

    records = []
    for key, fills in groups.items():
        first = min(fills, key=lambda e: e.get("trade_time") or "")
        total_qty = sum(abs(float(f.get("quantity") or 0)) for f in fills)
        notional = sum(abs(float(f.get("quantity") or 0)) * float(f.get("price") or 0) for f in fills)
        commissions = [f.get("commission") for f in fills if f.get("commission") is not None]
        amounts = [f.get("amount") for f in fills if f.get("amount") is not None]
        records.append(dict(
            first,
            record_id=key,
            quantity=total_qty,
            price=round(notional / total_qty, 6) if total_qty else first.get("price"),
            commission=sum(commissions) if commissions else None,
            amount=sum(amounts) if amounts else None,
            fills=len(fills),
        ))
    return records


def derive_fields(record: dict, synced_at: str) -> dict:
    values = dict(record)
    values["trade_date"] = (record.get("trade_time") or "")[:10]
    values["signed_quantity"] = _signed(record.get("quantity"), record.get("side"))
    values["fees"] = abs(record["commission"]) if record.get("commission") is not None else None
    values["synced_at"] = synced_at
    return values


def route_for(record: dict, routes: List[dict]) -> Optional[dict]:
    for route in routes:
        if all(_matches(record.get(key), expected) for key, expected in route["match"].items()):
            return route
    return None


def _matches(actual, expected) -> bool:
    options = expected if isinstance(expected, list) else [expected]
    return str(actual or "").upper() in {str(o).upper() for o in options}


# ── Rows ──────────────────────────────────────────────────────────────────────

def _norm(header) -> str:
    return str(header).strip().lower()


def mapped_width(sheet_headers: List[str], route: dict) -> int:
    """Number of columns from A up to the last header the route maps."""
    mapped = {_norm(c["header"]) for c in route["columns"]}
    indexes = [i for i, h in enumerate(sheet_headers) if _norm(h) in mapped]
    return max(indexes) + 1 if indexes else 0


def build_row(values: dict, sheet_headers: List[str], route: dict, width: int, id_field: str) -> list:
    by_header = {_norm(c["header"]): c for c in route["columns"]}
    row = []
    for header in sheet_headers[:width]:
        column = by_header.get(_norm(header))
        if column is None:
            row.append("")
        elif "value" in column:
            row.append(column["value"])
        else:
            value = values.get(column["field"])
            if column["field"] == "symbol" and value:
                value = f"{route['symbol_prefix']}{value}"
            if column["field"] == id_field and value is not None:
                value = f"'{value}"  # keep IDs as text (USER_ENTERED would turn digits into numbers)
            row.append("" if value is None else value)
    return row


def _manual_key(symbol, trade_date, quantity):
    try:
        quantity = round(float(str(quantity).replace(",", "")), 6)
    except ValueError:
        return None
    return str(symbol).strip().upper(), str(trade_date).strip()[:10], quantity


def column_letter(index: int) -> str:
    """0-based column index -> A1 column letters (0 -> A, 26 -> AA)."""
    letters = ""
    index += 1
    while index:
        index, remainder = divmod(index - 1, 26)
        letters = chr(65 + remainder) + letters
    return letters


# ── Summary rows (e.g. a "Running Quantities" block of formulas per symbol) ───

_REF = re.compile(
    r"(?P<prefix>(?:'[^']+'|[A-Za-z0-9_]+)!)?"
    r"\$?(?P<c1>[A-Z]{1,3})\$?(?P<r1>\d+)"
    r"(?::\$?(?P<c2>[A-Z]{1,3})\$?(?P<r2>\d+))?"
)


def adapt_formula(formula: str, source_row: int, target_row: int) -> str:
    """Rewrite a summary row's formula for another row.

    Only references local to the source row move: single cells on that row (``A2``) and
    ranges lying entirely on it (``B2:C2``). Ranges into the data (``'USD Buy
    History'!A2:A9998``, ``A2:A9999``) are kept, so every row reads the whole table.
    """
    def move(match):
        if match.group("prefix"):
            return match.group(0)
        r1, r2 = int(match.group("r1")), match.group("r2")
        if r2 is None:
            return f"{match.group('c1')}{target_row}" if r1 == source_row else match.group(0)
        if r1 == source_row and int(r2) == source_row:
            return f"{match.group('c1')}{target_row}:{match.group('c2')}{target_row}"
        return match.group(0)
    return _REF.sub(move, formula) if str(formula).startswith("=") else formula


def plan_summary(sheets, summary: dict, symbols: List[str]) -> dict:
    """Rows to add to a route's summary block for symbols it doesn't list yet (no writes).

    The block is found by its symbol column; formulas are generated from its FIRST data
    row (the pattern), so each new row covers the whole data table.
    """
    tab, col = summary["tab"], summary["symbol_column"]
    col_i = letter_index(col)
    header = (sheets.get_values(f"'{tab}'!{col}1:{column_letter(col_i + 25)}1") or [[]])[0]
    width = len(header)
    while width and not str(header[width - 1]).strip():
        width -= 1
    last_col = column_letter(col_i + max(width, 1) - 1)
    listed = sheets.get_values(f"'{tab}'!{col}2:{col}")
    existing = {str(r[0]).strip().upper() for r in listed if r and str(r[0]).strip()}
    used = max((n for n, r in enumerate(listed, start=2) if r and str(r[0]).strip()), default=1)

    wanted = []
    for symbol in symbols:
        if symbol and symbol.upper() not in existing and symbol.upper() not in {w.upper() for w in wanted}:
            wanted.append(symbol)
    if not wanted:
        return {"tab": tab, "rows": [], "symbols": []}
    if used < 2:
        raise ValueError(f"Summary block '{tab}'!{col} has no data row to copy formulas from.")

    pattern = sheets.spreadsheets.values().get(
        spreadsheetId=sheets.sheet_id, range=f"'{tab}'!{col}2:{last_col}2", valueRenderOption="FORMULA",
    ).execute().get("values", [[]])[0]
    rows = []
    for n, symbol in enumerate(wanted, start=used + 1):
        rows.append({"row": n, "range": f"'{tab}'!{col}{n}:{last_col}{n}",
                     "values": [symbol] + [adapt_formula(f, 2, n) for f in pattern[1:]]})
    # Never overwrite: the target cells must be empty.
    block = sheets.get_values(f"'{tab}'!{col}{used + 1}:{last_col}{used + len(rows)}")
    if any(str(c).strip() for row in block for c in row):
        raise ValueError(f"Summary block '{tab}'!{col}{used + 1} is not empty below the last symbol.")
    return {"tab": tab, "rows": rows, "symbols": wanted}


# ── Sync ──────────────────────────────────────────────────────────────────────

def _sheets_service(cfg_id__sheets: str):
    from apps.google_apps.references.web.api.sheets import ApiServiceGoogleSheets

    config = CONFIG_MANAGER.get(cfg_id__sheets)
    if not configured(config.app_data.get("sheet_id")):
        raise ValueError("TRADE_LOG_SHEET_ID is not set - run scripts/ibkr_trade_log.py create-sheet first.")
    return ApiServiceGoogleSheets(config, scopes_list=config.app_data["scopes"])


def plan_route(sheets, route: dict, records: List[dict], template: dict, synced_at: str) -> dict:
    """Work out which records this tab still needs (no writes)."""
    tab = route["tab"]
    header_rows = sheets.get_values(f"'{tab}'!1:1")
    sheet_headers = header_rows[0] if header_rows else []
    normalized = [_norm(h) for h in sheet_headers]
    if _norm(route["id_header"]) not in normalized:
        raise ValueError(f"Tab '{tab}' has no '{route['id_header']}' header - run prepare-sheet first.")

    width = mapped_width(sheet_headers, route)
    table = sheets.get_values(f"'{tab}'!A2:{column_letter(width - 1)}")
    id_index = normalized.index(_norm(route["id_header"]))

    def index_of(field):
        headers = {_norm(c["header"]) for c in route["columns"] if c.get("field") == field}
        return next((i for i, h in enumerate(normalized) if h in headers), None)

    sym_i, date_i, qty_i = index_of("symbol"), index_of("trade_date"), index_of("signed_quantity")
    existing_ids, manual_keys, symbols = set(), set(), set()
    for row in table:
        cell = lambda i: row[i] if i is not None and i < len(row) else ""
        if cell(id_index):
            existing_ids.add(str(cell(id_index)).strip())
        elif None not in (sym_i, date_i, qty_i):
            manual_keys.add(_manual_key(cell(sym_i), cell(date_i), cell(qty_i)))
        if cell(sym_i):
            symbols.add(str(cell(sym_i)).strip().upper())

    pending, already_manual, new_symbols = [], [], set()
    for record in records:
        values = derive_fields(record, synced_at)
        if str(values.get(template["id_field"])) in existing_ids:
            continue
        symbol = f"{route['symbol_prefix']}{values.get('symbol') or ''}".upper()
        if _manual_key(symbol, values["trade_date"], values["signed_quantity"]) in manual_keys:
            already_manual.append(values)
            continue
        if symbol not in symbols:
            new_symbols.add(symbol)
        pending.append(values)

    return {
        "tab": tab, "width": width, "headers": sheet_headers,
        "rows": [build_row(v, sheet_headers, route, width, template["id_field"]) for v in pending],
        "pending": pending, "already_manual": already_manual, "new_symbols": sorted(new_symbols),
    }


def sync_to_sheet(cfg_id__sheets: str = "GOOGLE_SHEETS_TRADE_LOG", template_file: Optional[Path] = None,
                  dry_run: bool = False, ledger_file: Optional[Path] = None,
                  cash_ledger_file: Optional[Path] = None) -> dict:
    """Append ledger trades (routed to their tabs) and deposits that are not yet in the sheet."""
    from apps.google_apps.references.web.api.sheets import SheetInputOption

    template = load_template(template_file)
    records = sorted(group_entries(load_ledger(ledger_file), template["group_by"]),
                     key=lambda r: r.get("trade_time") or "")

    by_route: Dict[str, List[dict]] = OrderedDict()
    unrouted = []
    for record in records:
        route = route_for(record, template["routes"])
        if route is None:
            unrouted.append(record)
        else:
            by_route.setdefault(route["tab"], []).append(record)

    sheets = _sheets_service(cfg_id__sheets)
    synced_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    routes = {r["tab"]: r for r in template["routes"]}
    tabs, lines, total = [], [], 0
    for tab, tab_records in by_route.items():
        route = routes[tab]
        plan = plan_route(sheets, route, tab_records, template, synced_at)
        if plan["rows"] and not dry_run:
            sheets.append_values(f"'{tab}'!A:{column_letter(plan['width'] - 1)}", plan["rows"],
                                 SheetInputOption.USER_ENTERED, insert_rows=False)
        summary_added, new_symbols = [], plan["new_symbols"]
        if route.get("summary"):
            symbols = [f"{route['symbol_prefix']}{v.get('symbol')}" for v in plan["pending"] if v.get("symbol")]
            summary = plan_summary(sheets, route["summary"], symbols)
            if not dry_run:
                for row in summary["rows"]:
                    sheets.update_values(row["range"], [row["values"]], SheetInputOption.USER_ENTERED)
            summary_added = [f"'{summary['tab']}' row {r['row']}: {r['values'][0]}" for r in summary["rows"]]
            new_symbols = []  # handled automatically
        total += len(plan["rows"])
        lines += [f"[{tab}] {describe(v)}" for v in plan["pending"]]
        tabs.append({"tab": tab, "new": len(plan["rows"]), "already_recorded_by_hand": len(plan["already_manual"]),
                     "new_symbols": new_symbols, "summary_added": summary_added})
    _log.info("sync_to_sheet: %s %d row(s)", "would append" if dry_run else "appended", total)
    deposits = sync_deposits(sheets, template, dry_run, cash_ledger_file)
    dividends = sync_dividends(sheets, template, dry_run, cash_ledger_file)

    return {
        "ledger": len(records), "new": total, "dry_run": dry_run, "trades": lines, "tabs": tabs,
        "unrouted": [describe(r) + f" ({r.get('currency')}, {r.get('listing_exchange') or r.get('exchange')})"
                     for r in unrouted],
        "deposits": deposits,
        "dividends": dividends,
    }


# ── Deposits / withdrawals ────────────────────────────────────────────────────

DEPOSIT_NOTE = "IBKR deposit (auto)"
WITHDRAWAL_NOTE = "IBKR withdrawal (auto)"


def derive_cash_fields(entry: dict) -> dict:
    values = dict(entry)
    values["record_id"] = entry.get("transaction_id")
    values["date"] = (entry.get("date_time") or "")[:10]
    values["note"] = WITHDRAWAL_NOTE if (entry.get("amount") or 0) < 0 else DEPOSIT_NOTE
    return values


def letter_index(letters: str) -> int:
    """A1 column letters -> 0-based index (A -> 0, AA -> 26)."""
    index = 0
    for char in letters.strip().upper():
        index = index * 26 + (ord(char) - 64)
    return index - 1


def resolve_columns(columns: List[dict], sheet_headers: List[str]) -> List[tuple]:
    """(index, column) per template column: by `column` letter, or by row-1 `header` text."""
    normalized = [_norm(h) for h in sheet_headers]
    resolved = []
    for column in columns:
        if "column" in column:
            resolved.append((letter_index(column["column"]), column))
        elif _norm(column["header"]) in normalized:
            resolved.append((normalized.index(_norm(column["header"])), column))
        else:
            raise ValueError(f"Header '{column['header']}' not found in row 1 - run prepare-sheet first.")
    return resolved


def _number(value) -> Optional[float]:
    try:
        return round(float(str(value).replace(",", "")), 2)
    except ValueError:
        return None


def plan_deposits(sheets, section: dict, entries: List[dict]) -> dict:
    """Work out which deposits the tab still needs and where to insert them (no writes)."""
    tab = section["tab"]
    header_rows = sheets.get_values(f"'{tab}'!1:1")
    sheet_headers = header_rows[0] if header_rows else []
    columns = resolve_columns(section["columns"], sheet_headers)
    width = max(i for i, _ in columns) + 1
    table = sheets.get_values(f"'{tab}'!A2:{column_letter(width - 1)}")

    index_of = {c.get("field"): i for i, c in columns if c.get("field")}
    id_i, date_i, amount_i = index_of.get("record_id"), index_of.get("date"), index_of.get("amount")

    def cell(row, i):
        return row[i] if i is not None and i < len(row) else ""

    existing_ids, manual_keys = set(), set()
    for row in table:
        if str(cell(row, id_i)).strip():
            existing_ids.add(str(cell(row, id_i)).strip().lstrip("'"))
        elif str(cell(row, amount_i)).strip():
            manual_keys.add((str(cell(row, date_i)).strip()[:10], _number(cell(row, amount_i))))

    # New rows go above the first blank row under the data (e.g. the spacer before a total),
    # so totals below are pushed down, never overwritten.
    blank = next((n for n, row in enumerate(table) if not any(str(c).strip() for c in row[:width])), len(table))
    insert_index = blank + 1 if section["insert_above_blank_row"] else len(table) + 1  # 0-based; row 1 = header

    pending, already_manual, unmatched = [], [], []
    for entry in sorted(entries, key=lambda e: e.get("date_time") or ""):
        values = derive_cash_fields(entry)
        if str(values["record_id"]) in existing_ids:
            continue
        if not all(_matches(values.get(k), v) for k, v in section["match"].items()):
            unmatched.append(values)
            continue
        if (values["date"], _number(values.get("amount"))) in manual_keys:
            already_manual.append(values)
            continue
        pending.append(values)

    rows = []
    for values in pending:
        row = [""] * width
        for i, column in columns:
            if "value" in column:
                row[i] = column["value"]
            else:
                value = values.get(column["field"])
                if column["field"] == "record_id" and value is not None:
                    value = f"'{value}"  # keep IDs as text
                row[i] = "" if value is None else value
        rows.append(row)
    return {"tab": tab, "width": width, "insert_index": insert_index, "rows": rows,
            "pending": pending, "already_manual": already_manual, "unmatched": unmatched}


def sync_deposits(sheets, template: dict, dry_run: bool = False, cash_ledger_file: Optional[Path] = None) -> dict:
    """Insert captured deposits/withdrawals that are not yet on the deposits tab."""
    from apps.google_apps.references.web.api.sheets import SheetInputOption

    section = template.get("deposits")
    entries = [e for e in load_ledger(cash_ledger_file or cash_ledger_path()) if e.get("type") == DEPOSIT_TYPE]
    if not section:
        return {"ledger": len(entries), "new": 0, "lines": [], "already_recorded_by_hand": 0, "unmatched": []}

    plan = plan_deposits(sheets, section, entries)
    if plan["rows"] and not dry_run:
        start = plan["insert_index"]
        sheets.insert_rows(plan["tab"], start, len(plan["rows"]))
        sheets.update_values(f"'{plan['tab']}'!A{start + 1}", plan["rows"], SheetInputOption.USER_ENTERED)
    _log.info("sync_deposits: %s %d row(s)", "would insert" if dry_run else "inserted", len(plan["rows"]))
    return {
        "ledger": len(entries), "new": len(plan["rows"]),
        "lines": [f"[{plan['tab']}] {describe_cash(v)} at row {plan['insert_index'] + 1 + n}"
                  for n, v in enumerate(plan["pending"])],
        "already_recorded_by_hand": len(plan["already_manual"]),
        "unmatched": [describe_cash(v) for v in plan["unmatched"]],
    }


# ── Dividends ─────────────────────────────────────────────────────────────────

INCOME_TYPES = ("Dividends", "Payment In Lieu Of Dividends")
TAX_TYPE = "Withholding Tax"


def group_dividends(entries: List[dict]) -> List[dict]:
    """One record per IBKR corporate action and payment date.

    A dividend, its withholding tax and same-day corrections share an action ID, so
    they net into one row (gross, tax, net). Corrections booked on a later date
    (e.g. a tax refund) become their own row, so written rows never need editing.
    """
    groups: "OrderedDict[tuple, List[dict]]" = OrderedDict()
    for entry in sorted(entries, key=lambda e: e.get("date_time") or ""):
        if entry.get("type") not in INCOME_TYPES + (TAX_TYPE,):
            continue
        day = (entry.get("date_time") or "")[:10]
        key = (entry.get("action_id") or entry.get("transaction_id"), day)
        groups.setdefault(key, []).append(entry)

    records = []
    for (action_id, day), rows in groups.items():
        income = [r for r in rows if r.get("type") in INCOME_TYPES]
        gross = round(sum(r.get("amount") or 0 for r in income), 6)
        tax = round(sum(r.get("amount") or 0 for r in rows if r.get("type") == TAX_TYPE), 6)
        main = income[0] if income else rows[0]
        fx = next((r.get("fx_rate_to_base") for r in rows if r.get("fx_rate_to_base")), None)
        if not income:
            kind = "Tax adjustment"
        elif all(r.get("type") == "Payment In Lieu Of Dividends" for r in income):
            kind = "Payment in lieu"
        else:
            kind = "Dividend"
        net = round(gross + tax, 6)
        records.append({
            "record_id": f"{action_id}-{day.replace('-', '')}",
            "pay_date": day,
            "ex_date": _iso_date(next((r.get("ex_date") for r in income if r.get("ex_date")), None)),
            "symbol": main.get("symbol"),
            "kind": kind,
            "currency": main.get("currency"),
            "gross": gross,
            "withholding_tax": tax,
            "net": net,
            "fx_rate_to_base": fx,
            "net_base": round(net * fx, 2) if fx else None,
            "description": main.get("description"),
        })
    return records


def _iso_date(value) -> Optional[str]:
    digits = "".join(ch for ch in str(value or "") if ch.isdigit())
    return f"{digits[:4]}-{digits[4:6]}-{digits[6:8]}" if len(digits) >= 8 else None


def plan_dividends(sheets, section: dict, records: List[dict], tab_exists: bool = True) -> dict:
    """Rows the dividends tab still needs, in the tab's column order (no writes)."""
    tab = section["tab"]
    if tab_exists:
        header_rows = sheets.get_values(f"'{tab}'!1:1")
        sheet_headers = header_rows[0] if header_rows else []
    else:
        sheet_headers = [c.get("header", "") for c in section["columns"]]
    columns = resolve_columns(section["columns"], sheet_headers)
    width = max(i for i, _ in columns) + 1
    id_i = next(i for i, c in columns if c.get("field") == "record_id")
    existing = set()
    if tab_exists:
        for row in sheets.get_values(f"'{tab}'!A2:{column_letter(width - 1)}"):
            if id_i < len(row) and str(row[id_i]).strip():
                existing.add(str(row[id_i]).strip().lstrip("'"))

    pending = [r for r in sorted(records, key=lambda r: r["pay_date"]) if r["record_id"] not in existing]
    rows = []
    for record in pending:
        row = [""] * width
        for i, column in columns:
            value = column["value"] if "value" in column else record.get(column["field"])
            if column.get("field") == "record_id" and value is not None:
                value = f"'{value}"
            row[i] = "" if value is None else value
        rows.append(row)
    return {"tab": tab, "width": width, "headers": sheet_headers, "rows": rows, "pending": pending}


def describe_dividend(record: dict) -> str:
    return (f"{record['pay_date']} {record.get('symbol')} {record['kind'].lower()} "
            f"{record.get('currency')} gross {record['gross']:g} tax {record['withholding_tax']:g} net {record['net']:g}")


def sync_dividends(sheets, template: dict, dry_run: bool = False, cash_ledger_file: Optional[Path] = None) -> dict:
    """Append dividend payouts that are not yet on the dividends tab (creating the tab if needed)."""
    from apps.google_apps.references.web.api.sheets import SheetInputOption

    section = template.get("dividends")
    records = group_dividends(load_ledger(cash_ledger_file or cash_ledger_path()))
    if not section:
        return {"ledger": len(records), "new": 0, "lines": [], "created_tab": False}

    tab_exists = section["tab"] in sheets.tab_titles()
    if not tab_exists and not section.get("create_if_missing", True):
        raise ValueError(f"Tab '{section['tab']}' does not exist - create it or set create_if_missing: true.")
    plan = plan_dividends(sheets, section, records, tab_exists)
    if not dry_run:
        if not tab_exists:
            sheets.add_tab(section["tab"])
            sheets.update_values(f"'{section['tab']}'!A1", [plan["headers"]])
        if plan["rows"]:
            sheets.append_values(f"'{section['tab']}'!A:{column_letter(plan['width'] - 1)}", plan["rows"],
                                 SheetInputOption.USER_ENTERED, insert_rows=False)
    _log.info("sync_dividends: %s %d row(s)", "would append" if dry_run else "appended", len(plan["rows"]))
    return {
        "ledger": len(records), "new": len(plan["rows"]), "created_tab": not tab_exists,
        "tab": section["tab"],
        "lines": [f"[{section['tab']}] {describe_dividend(r)}" for r in plan["pending"]],
    }


# ── Sheet setup ───────────────────────────────────────────────────────────────

def prepare_sheet(cfg_id__sheets: str = "GOOGLE_SHEETS_TRADE_LOG", template_file: Optional[Path] = None,
                  dry_run: bool = False) -> List[str]:
    """Add any template headers missing from an existing sheet's tabs (row 1 only).

    Each missing header goes into the first empty row-1 cell, scanning from column A,
    so existing columns and side-by-side blocks are never moved or overwritten.
    Columns the template maps by letter (e.g. a header-less date column A) count as taken.
    """
    template = load_template(template_file)
    sheets = _sheets_service(cfg_id__sheets)
    changes = []
    sections = list(template["routes"])
    if template.get("deposits"):
        sections.append(template["deposits"])
    for route in sections:
        tab = route["tab"]
        header_rows = sheets.get_values(f"'{tab}'!1:1")
        headers = list(header_rows[0]) if header_rows else []
        present = {_norm(h) for h in headers}
        reserved = {letter_index(c["column"]) for c in route["columns"] if "column" in c}
        for column in route["columns"]:
            if "header" not in column or _norm(column["header"]) in present:
                continue
            index = next((i for i, h in enumerate(headers) if not str(h).strip() and i not in reserved), None)
            if index is None:
                index = max([len(headers)] + [i + 1 for i in reserved])
            while len(headers) <= index:
                headers.append("")
            headers[index] = column["header"]
            present.add(_norm(column["header"]))
            cell = f"'{tab}'!{column_letter(index)}1"
            changes.append(f"{cell} = {column['header']}")
            if not dry_run:
                sheets.update_values(cell, [[column["header"]]])
    _log.info("prepare_sheet: %s %d header(s)", "would add" if dry_run else "added", len(changes))
    return changes


def create_sheet(cfg_id__sheets: str = "GOOGLE_SHEETS_TRADE_LOG", template_file: Optional[Path] = None) -> str:
    """Create a new spreadsheet from the template (one tab per route, frozen headers); returns its ID."""
    import httplib2
    from google_auth_httplib2 import AuthorizedHttp
    from googleapiclient.discovery import build

    from apps.google_apps.references.web.client import GoogleApiClient

    template = load_template(template_file)
    data = CONFIG_MANAGER.get(cfg_id__sheets).app_data
    creds = GoogleApiClient(data["scopes"], data["credentials"], data["storage"],
                            service_account=data.get("service_account")).authorize()
    service = build("sheets", "v4", http=AuthorizedHttp(creds, http=httplib2.Http()), cache_discovery=False)

    sections = list(template["routes"]) + [template[k] for k in ("deposits", "dividends") if template.get(k)]
    tabs = list(OrderedDict((r["tab"], r) for r in sections).values())
    sheet = service.spreadsheets().create(body={
        "properties": {"title": template["title"]},
        "sheets": [{"properties": {"title": r["tab"], "gridProperties": {"frozenRowCount": 1}}} for r in tabs],
    }, fields="spreadsheetId").execute()
    sheet_id = sheet["spreadsheetId"]
    for route in tabs:
        service.spreadsheets().values().update(
            spreadsheetId=sheet_id, range=f"'{route['tab']}'!A1", valueInputOption="RAW",
            body={"values": [[c.get("header", "") for c in route["columns"]]]},
        ).execute()
    _log.info("create_sheet: created %s", sheet_id)
    return sheet_id
