"""
workflows/finance/tasks/parse_transaction.py

Parses a bank statement PDF using Claude (Anthropic) and imports the extracted
transactions into YNAB, with automatic category matching and debit/credit detection.
"""

import json
import base64
from dataclasses import asdict
from pathlib import Path
from typing import Optional

from core.apps.sprout.app.celery import SPROUT
from core.apps.es_logging.app.elasticsearch import log_result
from core.utilities.logging.custom_logger import create_logger

from apps.apps_config import CONFIG_MANAGER
from apps.desktop.helpers.feed import feed
from apps.ynab.references.web.api.budgets import ApiServiceYNABBudgets
from apps.ynab.references.web.api.transactions import ApiServiceYNABTransactions
from apps.ynab.references.dto.transaction import (
    DtoSaveTransaction, DtoSaveSubTransaction, DtoSaveTransactionsWrapper,
)
from apps.ynab.references.constants import YNAB_MILLIUNITS
from apps.antropic.references.web.base_api_service import BaseApiServiceAnthropic

from workflows.finance.prompts import load_prompt

_log = create_logger("finance.parse_transaction")

_TRANSACTIONS_DIR = Path(__file__).resolve().parent.parent / "transactions"


# ── Helpers ───────────────────────────────────────────────────────────────────

def _read_pdf_as_base64(pdf_path: Path) -> str:
    with open(pdf_path, "rb") as f:
        return base64.standard_b64encode(f.read()).decode("utf-8")


def _parse_pdf_with_claude(pdf_path: Path, cfg_id__anthropic: str = "ANTHROPIC") -> list[dict]:
    """Send the PDF to Claude as a base64 document and return parsed transactions.

    Args:
        pdf_path:          Path to the PDF file.
        cfg_id__anthropic: Config key for the Anthropic service (default 'ANTHROPIC').
    """
    system_prompt = load_prompt("parse_transaction")
    pdf_b64 = _read_pdf_as_base64(pdf_path)

    cfg__anthropic = CONFIG_MANAGER.get(cfg_id__anthropic)
    client = BaseApiServiceAnthropic(cfg__anthropic)
    if not client.base_client:
        raise RuntimeError("Anthropic client failed to initialize")

    response = client._with_backoff(
        client.base_client.messages.create,
        model=client.model,
        max_tokens=8192,
        system=system_prompt,
        messages=[
            {
                "role": "user",
                "content": [
                    {
                        "type": "document",
                        "source": {
                            "type": "base64",
                            "media_type": "application/pdf",
                            "data": pdf_b64,
                        },
                    },
                    {
                        "type": "text",
                        "text": "Extract all transactions from this bank statement and return them as a JSON array per the instructions.",
                    },
                ],
            }
        ],
    )

    raw = response.content[0].text.strip()
    if raw.startswith("```"):
        raw = raw.split("```", 2)[1]
        if raw.startswith("json"):
            raw = raw[4:]
        raw = raw.rsplit("```", 1)[0].strip()

    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        # Response may have been truncated at token limit — attempt recovery by
        # closing the last incomplete object and the array.
        _log.warning("JSON parse failed — attempting truncation recovery")
        try:
            recovered = raw.rstrip().rstrip(",")
            if not recovered.endswith("]"):
                if not recovered.endswith("}"):
                    last_brace = recovered.rfind("}")
                    if last_brace != -1:
                        recovered = recovered[:last_brace + 1]
                recovered = recovered + "]"
            result = json.loads(recovered)
            _log.warning("Recovery succeeded — %d transaction(s) recovered", len(result))
            return result
        except json.JSONDecodeError as exc2:
            _log.error("Claude returned non-JSON response (recovery failed): %s", raw[:500])
            raise ValueError(f"Claude response could not be parsed as JSON: {exc2}") from exc2


def _resolve_budget_id(service: ApiServiceYNABBudgets, budget_name: str) -> str:
    """Resolve a budget name to its YNAB ID."""
    data = service.get_budgets()
    budgets = data.get("budgets", [])
    for b in budgets:
        if b.get("name", "").strip().lower() == budget_name.strip().lower():
            return b["id"]
    available = [b.get("name") for b in budgets]
    raise ValueError(f"Budget '{budget_name}' not found. Available: {available}")


def _resolve_account_id(service: ApiServiceYNABBudgets, budget_id: str, account_name: str) -> str:
    """Resolve an account name to its YNAB account ID."""
    data = service.get_accounts(budget_id)
    accounts = data.get("accounts", [])
    for a in accounts:
        if a.get("name", "").strip().lower() == account_name.strip().lower():
            return a["id"]
    available = [a.get("name") for a in accounts]
    raise ValueError(f"Account '{account_name}' not found. Available: {available}")


def _build_category_lookup(service: ApiServiceYNABBudgets, budget_id: str) -> dict[str, str]:
    """Return {category_name_lower: category_id} for fuzzy matching."""
    data = service.get_categories(budget_id)
    lookup = {}
    for group in data.get("category_groups", []):
        for cat in group.get("categories", []):
            name = cat.get("name", "")
            cat_id = cat.get("id")
            if name and cat_id:
                lookup[name.lower()] = cat_id
    return lookup


def _match_category(hint: Optional[str], category_lookup: dict[str, str]) -> Optional[str]:
    """Match a Claude category_hint against live YNAB category names.

    category_lookup is {category_name_lower: category_id} built from the real
    YNAB budget — no static map needed.

    Strategy (in order):
      1. Exact match on the full hint
      2. Hint is a substring of a YNAB category name
      3. Any word from the hint (≥4 chars) appears in a YNAB category name
    """
    if not hint or not category_lookup:
        return None

    hint_lower = hint.lower().strip()

    # 1. Exact match
    if hint_lower in category_lookup:
        _log.debug("Exact match: '%s'", hint)
        return category_lookup[hint_lower]

    # 2. Hint is a substring of a YNAB category name
    for cat_name, cat_id in category_lookup.items():
        if hint_lower in cat_name:
            _log.debug("Substring match: '%s' in '%s'", hint, cat_name)
            return cat_id

    # 3. Any significant word in the hint appears in a YNAB category name
    words = [w for w in hint_lower.split() if len(w) >= 4]
    for word in words:
        for cat_name, cat_id in category_lookup.items():
            if word in cat_name:
                _log.debug("Word match: '%s' (from '%s') in '%s'", word, hint, cat_name)
                return cat_id

    return None


def _to_ynab_amount(amount: float, tx_type: str) -> int:
    """Convert a positive float amount to YNAB milliunits with correct sign.

    Debit (outflow) → negative milliunits.
    Credit (inflow) → positive milliunits.
    """
    milliunits = round(float(amount) * YNAB_MILLIUNITS)
    if tx_type == "credit":
        return abs(milliunits)
    return -abs(milliunits)  # debit or unknown → outflow


def _build_dto(tx: dict, account_id: str, category_lookup: dict[str, str]) -> Optional[DtoSaveTransaction]:
    """Build a DtoSaveTransaction from a parsed transaction dict. Returns None on bad data."""
    try:
        date = tx.get("date")
        memo = tx.get("memo") or ""
        amount_raw = tx.get("amount")
        tx_type = (tx.get("type") or "unknown").lower()
        payee_name = tx.get("payee_name")
        category_hint = tx.get("category_hint")

        if not date or amount_raw is None:
            _log.warning("Skipping transaction missing date or amount: %s", tx)
            return None

        amount = _to_ynab_amount(float(amount_raw), tx_type)
        category_id = _match_category(category_hint, category_lookup)

        return DtoSaveTransaction(
            account_id=account_id,
            date=date,
            amount=amount,
            payee_name=payee_name,
            category_id=category_id,
            memo=memo[:200],
            cleared="uncleared",
            approved=False,
        )
    except (TypeError, ValueError) as exc:
        _log.error("Failed to build DTO for transaction %s: %s", tx, exc)
        return None


def _build_split_dto(parsed_transactions: list[dict], account_id: str,
                     category_lookup: dict[str, str], pdf_name: str) -> DtoSaveTransaction:
    """Build a single split DtoSaveTransaction from all parsed transactions.

    Each parsed transaction becomes a subtransaction. The parent transaction:
      - date  = earliest date found across all transactions
      - amount = sum of all subtransaction amounts (YNAB requires these to match)
      - memo  = PDF filename as the import reference

    Args:
        parsed_transactions: Raw transaction dicts from Claude.
        account_id:          Resolved YNAB account ID.
        category_lookup:     Live {category_name_lower: category_id} from YNAB.
        pdf_name:            PDF filename used as the parent memo.
    """
    subtransactions = []
    skipped = 0

    for tx in parsed_transactions:
        try:
            memo = (tx.get("memo") or "")[:200]
            amount_raw = tx.get("amount")
            tx_type = (tx.get("type") or "unknown").lower()
            payee_name = tx.get("payee_name")
            category_hint = tx.get("category_hint")

            if amount_raw is None:
                _log.warning("Skipping subtransaction missing amount: %s", tx)
                skipped += 1
                continue

            subtransactions.append(DtoSaveSubTransaction(
                amount=_to_ynab_amount(float(amount_raw), tx_type),
                payee_name=payee_name,
                category_id=_match_category(category_hint, category_lookup),
                memo=memo,
            ))
        except (TypeError, ValueError) as exc:
            _log.error("Failed to build subtransaction for %s: %s", tx, exc)
            skipped += 1

    if not subtransactions:
        raise ValueError("No valid subtransactions could be built from the parsed PDF.")

    # Parent amount must equal the sum of all subtransaction amounts
    total_amount = sum(s.amount for s in subtransactions)

    # Use the earliest date found across all transactions
    dates = [tx.get("date") for tx in parsed_transactions if tx.get("date")]
    parent_date = min(dates) if dates else None
    if not parent_date:
        raise ValueError("No valid dates found in parsed transactions.")

    _log.info("Built split transaction: %d subtransaction(s), %d skipped, total=%d milliunits",
              len(subtransactions), skipped, total_amount)

    return DtoSaveTransaction(
        account_id=account_id,
        date=parent_date,
        amount=total_amount,
        memo=f"PDF Import: {pdf_name}"[:200],
        cleared="uncleared",
        approved=False,
        subtransactions=subtransactions,
    )


# ── Task ──────────────────────────────────────────────────────────────────────

@log_result()
@feed()
def add_ynab_transactions_from_pdf(input_pdf: str, ynab_budget_name: str,
                                   ynab_account_name: str, split: bool = False, **kwargs):
    """Parse a bank statement PDF and import transactions into YNAB.

    Args:
        input_pdf:           PDF filename inside workflows/finance/transactions/.
        ynab_budget_name:    YNAB budget name as shown in the app (e.g. 'SGD Budget').
        ynab_account_name:   YNAB account name within that budget (e.g. 'DBS Checking').
        split:               If True, import the entire PDF as a single YNAB split
                             transaction where each line becomes a subtransaction.
                             If False (default), import each line as its own transaction.
        cfg_id__ynab:        Config key for YNAB (default 'YNAB').
        cfg_id__anthropic:   Config key for Anthropic (default 'ANTHROPIC').

    Returns:
        Summary string of how many transactions were imported.
    """
    cfg_id__ynab = kwargs.get("cfg_id__ynab", "YNAB")
    cfg_id__anthropic = kwargs.get("cfg_id__anthropic", "ANTHROPIC")

    cfg__ynab = CONFIG_MANAGER.get(cfg_id__ynab)

    # ── Resolve PDF path ──────────────────────────────────────────────────
    pdf_path = _TRANSACTIONS_DIR / input_pdf
    if not pdf_path.exists():
        raise FileNotFoundError(f"PDF not found: {pdf_path}")
    _log.info("Parsing PDF: %s (split=%s)", pdf_path, split)

    # ── Parse PDF via Claude ──────────────────────────────────────────────
    try:
        parsed_transactions = _parse_pdf_with_claude(pdf_path, cfg_id__anthropic=cfg_id__anthropic)
    except Exception as exc:
        _log.error("PDF parsing failed: %s", exc)
        raise

    _log.info("Claude extracted %d transaction(s) from PDF", len(parsed_transactions))

    if not parsed_transactions:
        return "No transactions extracted from PDF."

    # ── Resolve YNAB budget + account IDs ────────────────────────────────
    budget_service = ApiServiceYNABBudgets(cfg__ynab)

    try:
        budget_id = _resolve_budget_id(budget_service, ynab_budget_name)
    except ValueError as exc:
        _log.error("Budget resolution failed: %s", exc)
        raise

    try:
        account_id = _resolve_account_id(budget_service, budget_id, ynab_account_name)
    except ValueError as exc:
        _log.error("Account resolution failed: %s", exc)
        raise

    _log.info("Resolved budget '%s' → %s, account '%s' → %s",
              ynab_budget_name, budget_id, ynab_account_name, account_id)

    # ── Build category lookup for matching ────────────────────────────────
    category_lookup = _build_category_lookup(budget_service, budget_id)
    _log.info("Loaded %d YNAB categories for matching", len(category_lookup))

    # ── Build payload ─────────────────────────────────────────────────────
    tx_service = ApiServiceYNABTransactions(cfg__ynab)

    if split:
        # One parent transaction with all lines as subtransactions
        try:
            split_dto = _build_split_dto(parsed_transactions, account_id, category_lookup, input_pdf)
        except ValueError as exc:
            _log.error("Split transaction build failed: %s", exc)
            raise

        payload = {"transaction": asdict(split_dto)}

        try:
            result = tx_service.create_new_transaction(budget_id, payload)
        except Exception as exc:
            _log.error("YNAB create_new_transaction (split) failed: %s", exc)
            raise

        sub_count = len(split_dto.subtransactions)
        summary = (
            f"Imported 1 split transaction ({sub_count} subtransaction(s)) "
            f"from '{input_pdf}' into {ynab_budget_name} / {ynab_account_name}."
        )

    else:
        # Individual transaction per line
        dtos = []
        skipped = 0
        for tx in parsed_transactions:
            dto = _build_dto(tx, account_id, category_lookup)
            if dto is not None:
                dtos.append(dto)
            else:
                skipped += 1

        _log.info("Built %d DTO(s), skipped %d", len(dtos), skipped)

        if not dtos:
            return f"All {len(parsed_transactions)} transactions were skipped (missing date or amount)."

        wrapper_dict = asdict(DtoSaveTransactionsWrapper(transactions=dtos))
        wrapper_dict.pop("transaction", None)

        try:
            result = tx_service.create_new_transaction(budget_id, wrapper_dict)
        except Exception as exc:
            _log.error("YNAB create_new_transaction failed: %s", exc)
            raise

        imported = len(result.get("transactions", result.get("transaction", [])) or [])
        duplicates = len(result.get("duplicate_import_ids", []))
        summary = (
            f"Imported {imported} transaction(s) from '{input_pdf}' "
            f"into {ynab_budget_name} / {ynab_account_name}. "
            f"Skipped (parse): {skipped}. Duplicates: {duplicates}."
        )

    _log.info(summary)
    return summary
