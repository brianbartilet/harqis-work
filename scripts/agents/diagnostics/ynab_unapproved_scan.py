#!/usr/bin/env python3
"""Weekly YNAB unapproved-transaction scan for Hermes cron.

Usage:
    python scripts/agents/diagnostics/ynab_unapproved_scan.py

Notification contract:
- stdout is empty when there are no matching unapproved transactions (silent success)
- stdout contains the Telegram-ready digest when matching unapproved transactions exist
- non-zero exit means Hermes sends an error alert
"""
from __future__ import annotations

import contextlib
import io
import os
import sys
from collections import defaultdict
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, cast

# scripts/agents/diagnostics/<script>.py → repo root is parents[3]
REPO_ROOT = Path(__file__).resolve().parents[3]
REPO_PYTHON = REPO_ROOT / ".venv" / "bin" / "python"

BUDGET_NAMES = {
    "Daily Bankroll - PHP",
    "Daily Bankroll - SGD",
}
LOOKBACK_DAYS = 30

if (
    not os.environ.get("YNAB_SCAN_REEXEC_DONE")
    and REPO_PYTHON.exists()
    and Path(sys.executable).resolve() != REPO_PYTHON.resolve()
):
    env = os.environ.copy()
    env["YNAB_SCAN_REEXEC_DONE"] = "1"
    os.execve(str(REPO_PYTHON), [str(REPO_PYTHON), __file__, *sys.argv[1:]], env)


def _setup_repo_env() -> None:
    os.chdir(REPO_ROOT)
    sys.path.insert(0, str(REPO_ROOT))
    from scripts.launch import setup_env  # noqa: WPS433

    setup_env()


def _amount_text(tx: dict, budget: dict) -> str:
    formatted = tx.get("amount_formatted")
    if formatted:
        return str(formatted)
    amount = tx.get("amount")
    if amount is None:
        return "?"
    iso = (budget.get("currency_format") or {}).get("iso_code") or ""
    value = amount / 1000
    return f"{iso} {value:,.2f}".strip()


def _safe(value: object, fallback: str = "—") -> str:
    if value is None:
        return fallback
    text = str(value).strip()
    return text if text else fallback


def _tx_date(tx: dict) -> date | None:
    raw = tx.get("date")
    if not raw:
        return None
    try:
        return date.fromisoformat(str(raw)[:10])
    except ValueError:
        return None


def _response_payload(response: Any) -> dict[str, Any]:
    """Return deserialized YNAB payload, or raise a concise API error."""
    if isinstance(response, dict):
        return response
    data = getattr(response, "data", None)
    if isinstance(data, dict):
        if "error" in data:
            error = data.get("error") or {}
            detail = error.get("detail") or error.get("name") or error.get("id") or "unknown error"
            raise RuntimeError(f"YNAB API error: {detail}")
        return cast(dict[str, Any], data.get("data") if isinstance(data.get("data"), dict) else data)
    raise TypeError(f"Unexpected YNAB API response type: {type(response).__name__}")


def _line_for(tx: dict, budget: dict) -> str:
    tx_day = _tx_date(tx)
    day = tx_day.strftime("%m-%d") if tx_day else _safe(tx.get("date"))
    amount = _amount_text(tx, budget)
    payee = _safe(tx.get("payee_name") or tx.get("import_payee_name"), "No payee")
    category = _safe(tx.get("category_name"), "Uncategorized")
    return f"  • {day} · {amount} · {payee} · {category}"


def _scan() -> tuple[list[dict], list[tuple[dict, list[dict]]], int, date]:
    """Run the HARQIS YNAB API scan while routing noisy app logs to stderr."""
    _setup_repo_env()

    from apps.ynab.config import CONFIG  # noqa: WPS433
    from apps.ynab.references.web.api.budgets import ApiServiceYNABBudgets  # noqa: WPS433
    from apps.ynab.references.web.api.transactions import ApiServiceYNABTransactions  # noqa: WPS433

    budget_service = ApiServiceYNABBudgets(CONFIG)
    transaction_service = ApiServiceYNABTransactions(CONFIG)

    cutoff = date.today() - timedelta(days=LOOKBACK_DAYS)
    budget_response = _response_payload(budget_service.get_budgets())
    all_budgets = cast(list[dict[str, Any]], budget_response.get("budgets", []))
    budgets = [
        budget
        for budget in all_budgets
        if not budget.get("deleted") and budget.get("name") in BUDGET_NAMES
    ]

    results: list[tuple[dict, list[dict]]] = []
    scanned_transactions = 0
    for budget in sorted(budgets, key=lambda item: item.get("name") or ""):
        budget_id = budget.get("id")
        if not budget_id:
            continue
        transaction_response = _response_payload(transaction_service.get_transactions(budget_id))
        transactions = cast(list[dict[str, Any]], transaction_response.get("transactions", []))
        recent_transactions = [
            tx for tx in transactions
            if not tx.get("deleted") and (tx_day := _tx_date(tx)) is not None and tx_day >= cutoff
        ]
        scanned_transactions += len(recent_transactions)
        unapproved = [
            tx for tx in recent_transactions
            if tx.get("approved") is False
        ]
        unapproved.sort(
            key=lambda tx: (
                tx.get("date") or "",
                tx.get("account_name") or "",
                tx.get("payee_name") or "",
            ),
            reverse=True,
        )
        if unapproved:
            results.append((budget, unapproved))
    return budgets, results, scanned_transactions, cutoff


def main() -> int:
    noisy_stdout = io.StringIO()
    with contextlib.redirect_stdout(noisy_stdout):
        budgets, results, scanned_transactions, cutoff = _scan()
    if noisy_stdout.getvalue().strip():
        print(noisy_stdout.getvalue().rstrip(), file=sys.stderr)

    total_unapproved = sum(len(items) for _, items in results)
    if total_unapproved == 0:
        return 0

    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    budget_label = ", ".join(sorted(BUDGET_NAMES))
    lines = [
        "💸 YNAB unapproved transactions",
        f"{now} · last {LOOKBACK_DAYS} days since {cutoff.isoformat()}",
        f"{total_unapproved} unapproved · {len(results)}/{len(budgets)} target budgets · {scanned_transactions} recent transactions scanned",
        f"Budgets: {budget_label}",
        "━━━━━━━━━━━━━━━━━━━━",
    ]

    for budget, items in results:
        budget_name = _safe(budget.get("name"), "Unnamed budget")
        lines.append(f"{budget_name} — {len(items)}")
        by_account: dict[str, list[dict]] = defaultdict(list)
        for tx in items:
            by_account[_safe(tx.get("account_name"), "Unknown account")].append(tx)
        for account_name in sorted(by_account):
            account_items = by_account[account_name]
            lines.append(f"{account_name} ({len(account_items)})")
            for tx in account_items:
                lines.append(_line_for(tx, budget))
        lines.append("━━━━━━━━━━━━━━━━━━━━")

    print("\n".join(lines).rstrip("━\n"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
