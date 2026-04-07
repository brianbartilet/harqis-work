from workflows.finance.tasks.parse_transaction import (
    add_ynab_transactions_from_pdf,
    _to_ynab_amount,
    _match_category,
    _build_dto,
)
from apps.ynab.references.dto.transaction import DtoSaveTransaction


# ── Full workflow tests ───────────────────────────────────────────────────────
# These call the real Anthropic + YNAB APIs.
# Place the PDF in workflows/finance/transactions/ before running.

def test__add_ynab_transactions_from_pdf__sgd():
    add_ynab_transactions_from_pdf(
        input_pdf="transaction_history_07042026_223941.pdf",
        ynab_budget_name="HARQIS Testing",
        ynab_account_name="Test Account",
        cfg_id__ynab="YNAB",
        cfg_id__anthropic="ANTHROPIC",
    )


def test__add_ynab_transactions_from_pdf__php():
    add_ynab_transactions_from_pdf(
        input_pdf="transaction_history_07042026_224029.pdf",
        ynab_budget_name="HARQIS Testing",
        ynab_account_name="Test Account Credit",
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
