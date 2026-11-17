import json
from datetime import date, datetime

import pytest

from workflows.finance.ibkr_ledger import (
    capture_trades,
    select_new_trades,
    select_new_cash,
    date_ranges,
    to_cash_ledger_entry,
    fill_key,
    to_ledger_entry,
    load_ledger,
    resolve_start_date,
    configured,
)
from apps.ibkr.references.dto.trade import DtoIbkrCashTransaction, DtoIbkrTrade


# ── Workflow (integration) ────────────────────────────────────────────────────
# Calls the real IBKR Flex Web Service.

def test__capture_trades_dry_run():
    result = capture_trades(cfg_id__ibkr='IBKR', dry_run=True)
    assert result["dry_run"] is True
    assert result["new"] == len(result["trades"])


@pytest.mark.skip(reason="Manual only — appends new IBKR trades to the local ledger")
def test__capture_ibkr_trades():
    from workflows.finance.tasks.ibkr_trades import capture_ibkr_trades
    capture_ibkr_trades(cfg_id__ibkr='IBKR')


# ── Unit / function ───────────────────────────────────────────────────────────

def _trade(trade_id, category="STK", when=datetime(2026, 10, 16, 10, 15), symbol="AAPL"):
    return DtoIbkrTrade(trade_id=trade_id, asset_category=category, symbol=symbol,
                        side="BUY", quantity=10.0, price=230.5, trade_time=when)


def test__select_new_trades_keeps_new_stocks_from_start_date():
    trades = [
        _trade("e1"),
        _trade("e2", category="OPT"),
        _trade("e3", when=datetime(2026, 10, 15, 15, 59), symbol="MSFT"),
    ]
    result = select_new_trades(trades, existing_ids=set(), start=date(2026, 10, 16))
    assert [t.trade_id for t in result] == ["e1"]


def test__select_new_trades_skips_existing_and_duplicate_ids():
    trades = [_trade("e1"), _trade("e1"), _trade("e2")]
    result = select_new_trades(trades, existing_ids={"e2"}, start=date(2026, 10, 16))
    assert [t.trade_id for t in result] == ["e1"]


def test__select_new_trades_dedupes_same_fill_from_both_reports():
    confirm = _trade("e1")                                  # Trade Confirmation report
    activity = _trade("other-id")                           # same fill, Activity report
    result = select_new_trades([confirm, activity], existing_ids=set(), start=date(2026, 10, 16))
    assert [t.trade_id for t in result] == ["e1"]


def test__select_new_trades_skips_fill_already_in_ledger_under_other_id():
    key = fill_key("AAPL", "2026-10-16 10:15:00", 10.0, 230.5)
    result = select_new_trades([_trade("new-id")], existing_ids=set(), start=date(2026, 10, 16),
                               existing_keys={key})
    assert result == []


def test__select_new_trades_oldest_first():
    trades = [_trade("late", when=datetime(2026, 10, 16, 15, 0)), _trade("early")]
    result = select_new_trades(trades, existing_ids=set(), start=date(2026, 10, 16))
    assert [t.trade_id for t in result] == ["early", "late"]


def test__select_new_trades_empty_input():
    assert select_new_trades([], existing_ids=set(), start=date(2026, 10, 16)) == []


def test__to_ledger_entry_round_trips_through_json(tmp_path):
    entry = to_ledger_entry(_trade("e1"), "2026-10-17 09:00:00")
    ledger = tmp_path / "ibkr_trades.jsonl"
    ledger.write_text(json.dumps(entry) + "\n", encoding="utf-8")
    loaded = load_ledger(ledger)
    assert loaded[0]["trade_id"] == "e1"
    assert loaded[0]["trade_time"] == "2026-10-16 10:15:00"
    assert loaded[0]["captured_at"] == "2026-10-17 09:00:00"


def test__load_ledger_missing_file(tmp_path):
    assert load_ledger(tmp_path / "missing.jsonl") == []


def test__resolve_start_date():
    assert resolve_start_date("2026-10-16") == date(2026, 10, 16)


def test__configured_treats_unset_placeholders_as_empty():
    assert configured("${IBKR_FLEX_TOKEN}") == ""
    assert configured(" abc ") == "abc"
    assert configured(None) == ""


def _cash(txn_id, amount=2500.0, currency="SGD", when=datetime(2026, 10, 14, 13, 13), txn_type="Deposits/Withdrawals"):
    return DtoIbkrCashTransaction(transaction_id=txn_id, type=txn_type, currency=currency, amount=amount, date_time=when)


def test__select_new_cash_filters_type_date_and_existing():
    txns = [_cash("d1"), _cash("d2", txn_type="Other Fees"), _cash("d3", when=datetime(2026, 10, 1)), _cash("d4"),
            _cash("d5", txn_type="Dividends")]
    result = select_new_cash(txns, existing_ids={"d4"}, start=date(2026, 10, 12))
    assert [t.transaction_id for t in result] == ["d1", "d5"]


def test__select_new_cash_limits_types():
    txns = [_cash("d1"), _cash("d5", txn_type="Dividends")]
    result = select_new_cash(txns, existing_ids=set(), start=date(2026, 10, 12), types=["Dividends"])
    assert [t.transaction_id for t in result] == ["d5"]


def test__date_ranges_chunks_by_365_days():
    assert date_ranges(date(2025, 1, 1), date(2026, 10, 16)) == [("20250101", "20251231"), ("20260101", "20261016")]
    assert date_ranges(date(2026, 10, 1), date(2026, 10, 1)) == [("20261001", "20261001")]


def test__to_cash_ledger_entry_serialises_date():
    entry = to_cash_ledger_entry(_cash("d1"), "2026-10-17 09:00:00")
    assert entry["date_time"] == "2026-10-14 13:13:00"
    assert json.loads(json.dumps(entry))["transaction_id"] == "d1"
