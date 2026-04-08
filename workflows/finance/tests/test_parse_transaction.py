from workflows.finance.tasks.parse_transaction import (
    add_ynab_transactions_from_pdf,
    _to_ynab_amount,
    _match_category,
    _build_dto,
    _build_split_dto,
)
from apps.ynab.references.dto.transaction import DtoSaveTransaction


# ── Full workflow tests ───────────────────────────────────────────────────────
# These call the real Anthropic + YNAB APIs.
# Place the PDF in workflows/finance/transactions/ before running.

def test__add_ynab_transactions_from_pdf_debit():
    add_ynab_transactions_from_pdf(
        input_pdf="transaction_history_07042026_223941.pdf",
        ynab_budget_name="HARQIS Testing",
        ynab_account_name="Test Account",
        cfg_id__ynab="YNAB",
        cfg_id__anthropic="ANTHROPIC",
    )


def test__add_ynab_transactions_from_pdf_credit():
    add_ynab_transactions_from_pdf(
        input_pdf="transaction_history_07042026_224029.pdf",
        ynab_budget_name="HARQIS Testing",
        ynab_account_name="Test Account Credit",
        cfg_id__ynab="YNAB",
        cfg_id__anthropic="ANTHROPIC",
    )


def test__add_ynab_transactions_from_pdf_split():
    add_ynab_transactions_from_pdf(
        input_pdf="transaction_history_07042026_223941.pdf",
        ynab_budget_name="HARQIS Testing",
        ynab_account_name="Test Account",
        split=True,
        cfg_id__ynab="YNAB",
        cfg_id__anthropic="ANTHROPIC",
    )


# ── Helper unit tests ─────────────────────────────────────────────────────────

def test__to_ynab_amount__debit():
    assert _to_ynab_amount(24.50, "debit") == -24500


def test__to_ynab_amount__credit():
    assert _to_ynab_amount(5000.00, "credit") == 5000000


def test__to_ynab_amount__unknown_is_outflow():
    assert _to_ynab_amount(100.00, "unknown") < 0


def test__match_category__exact_match():
    lookup = {"groceries": "cat-001", "transport": "cat-002"}
    assert _match_category("Groceries", lookup) == "cat-001"


def test__match_category__hint_substring_of_ynab_name():
    # "Dining Out" is a substring of the YNAB category "Dining Out & Restaurants"
    lookup = {"dining out & restaurants": "cat-010", "salary income": "cat-020"}
    assert _match_category("Dining Out", lookup) == "cat-010"


def test__match_category__word_match():
    # "Transport" word appears inside "Public Transport"
    lookup = {"public transport": "cat-030"}
    assert _match_category("Transport", lookup) == "cat-030"


def test__match_category__no_match_returns_none():
    assert _match_category("Completely Unknown XYZ", {"groceries": "cat-001"}) is None


def test__match_category__none_returns_none():
    assert _match_category(None, {"groceries": "cat-001"}) is None


def test__build_dto__debit():
    tx = {"date": "2026-04-01", "memo": "GRAB SG", "amount": 15.50,
          "type": "debit", "payee_name": "Grab", "category_hint": "Transport"}
    dto = _build_dto(tx, "acc-123", {"transport": "cat-transport"})
    assert isinstance(dto, DtoSaveTransaction)
    assert dto.amount == -15500
    assert dto.memo == "GRAB SG"
    assert dto.payee_name == "Grab"


def test__build_dto__missing_date_returns_none():
    assert _build_dto({"date": None, "memo": "X", "amount": 10.0, "type": "debit"}, "acc", {}) is None


def test__build_dto__missing_amount_returns_none():
    assert _build_dto({"date": "2026-04-01", "memo": "X", "amount": None, "type": "debit"}, "acc", {}) is None


def test__build_dto__memo_truncated():
    tx = {"date": "2026-04-01", "memo": "X" * 250, "amount": 5.0, "type": "debit",
          "payee_name": None, "category_hint": None}
    dto = _build_dto(tx, "acc-123", {})
    assert len(dto.memo) <= 200


def test__build_split_dto__total_amount_equals_sum():
    txs = [
        {"date": "2026-04-01", "memo": "GRAB", "amount": 10.0, "type": "debit", "payee_name": "Grab", "category_hint": None},
        {"date": "2026-04-02", "memo": "SALARY", "amount": 5000.0, "type": "credit", "payee_name": "Employer", "category_hint": None},
        {"date": "2026-04-03", "memo": "NTUC", "amount": 25.50, "type": "debit", "payee_name": "NTUC", "category_hint": None},
    ]
    dto = _build_split_dto(txs, "acc-123", {}, "statement.pdf")
    assert dto.amount == sum(s.amount for s in dto.subtransactions)
    assert len(dto.subtransactions) == 3
    assert dto.date == "2026-04-01"   # earliest date
    assert "statement.pdf" in dto.memo


def test__build_split_dto__skips_missing_amount():
    txs = [
        {"date": "2026-04-01", "memo": "GRAB", "amount": 10.0, "type": "debit", "payee_name": None, "category_hint": None},
        {"date": "2026-04-01", "memo": "BAD", "amount": None, "type": "debit", "payee_name": None, "category_hint": None},
    ]
    dto = _build_split_dto(txs, "acc-123", {}, "statement.pdf")
    assert len(dto.subtransactions) == 1
