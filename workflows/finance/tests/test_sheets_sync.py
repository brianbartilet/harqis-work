import pytest

from workflows.finance.sheets_sync import (
    sync_to_sheet,
    load_template,
    group_entries,
    derive_fields,
    route_for,
    build_row,
    mapped_width,
    plan_route,
    column_letter,
    plan_deposits,
    letter_index,
    group_dividends,
    plan_dividends,
    adapt_formula,
    plan_summary,
    DEFAULT_TEMPLATE,
)


# ── Workflow (integration) ────────────────────────────────────────────────────
# Calls the real Google Sheets API.

def test__sync_to_sheet_dry_run():
    result = sync_to_sheet(cfg_id__sheets='GOOGLE_SHEETS_TRADE_LOG', dry_run=True)
    assert result["dry_run"] is True
    assert result["new"] == len(result["trades"])


@pytest.mark.skip(reason="Manual only — appends ledger trades to the live trade log sheet")
def test__sync_trade_log_sheet():
    from workflows.finance.tasks.trade_log_sheet import sync_trade_log_sheet
    sync_trade_log_sheet(cfg_id__sheets='GOOGLE_SHEETS_TRADE_LOG')


# ── Unit / function ───────────────────────────────────────────────────────────

def _fill(trade_id, order_id="O1", symbol="NVDA", side="BUY", quantity=3, price=180.0,
          currency="USD", commission=-0.6, when="2026-10-16 22:40:00"):
    return {"trade_id": trade_id, "order_id": order_id, "symbol": symbol, "side": side, "quantity": quantity,
            "price": price, "currency": currency, "commission": commission, "trade_time": when}


_ROUTES_TEMPLATE = {
    "group_by": "order", "id_field": "record_id",
    "routes": [
        {"tab": "USD", "match": {"currency": "USD"}, "symbol_prefix": "", "id_header": "IBKR Trade ID",
         "columns": [{"header": "Symbol", "field": "symbol"}, {"header": "Date", "field": "trade_date"},
                     {"header": "Quantity", "field": "signed_quantity"}, {"header": "Price", "field": "price"},
                     {"header": "Fees", "field": "fees"}, {"header": "IBKR Trade ID", "field": "record_id"}]},
        {"tab": "SGD", "match": {"currency": ["SGD"]}, "symbol_prefix": "SGX: ", "id_header": "IBKR Trade ID",
         "columns": [{"header": "Symbol", "field": "symbol"}, {"header": "Platform", "value": "IBKR"},
                     {"header": "IBKR Trade ID", "field": "record_id"}]},
    ],
}


class _FakeSheets:
    def __init__(self, headers, rows):
        self.headers, self.rows = headers, rows

    def get_values(self, rng):
        return [self.headers] if rng.endswith("!1:1") else self.rows


def test__load_template_default():
    template = load_template(DEFAULT_TEMPLATE)
    assert template["routes"][0]["tab"] == "Trades"
    assert template["routes"][0]["id_header"] == "Trade ID"


def test__group_entries_by_order_combines_fills():
    records = group_entries([_fill("x1"), _fill("x2", quantity=2, price=181.0, commission=-0.4)], "order")
    assert len(records) == 1
    assert records[0]["record_id"] == "O1"
    assert records[0]["quantity"] == 5
    assert records[0]["price"] == pytest.approx(180.4)
    assert records[0]["commission"] == pytest.approx(-1.0)


def test__group_entries_by_execution_keeps_fills():
    records = group_entries([_fill("x1"), _fill("x2")], "execution")
    assert [r["record_id"] for r in records] == ["x1", "x2"]


def test__derive_fields_sell_is_negative_and_fees_positive():
    values = derive_fields(_fill("x1", side="SELL", quantity=-5, commission=-1.0), "now")
    assert values["signed_quantity"] == -5
    assert values["fees"] == 1.0
    assert values["trade_date"] == "2026-10-16"


def test__route_for_matches_first_route_and_reports_none():
    routes = _ROUTES_TEMPLATE["routes"]
    assert route_for(_fill("x1"), routes)["tab"] == "USD"
    assert route_for(_fill("x1", currency="sgd"), routes)["tab"] == "SGD"
    assert route_for(_fill("x1", currency="HKD"), routes) is None


def test__build_row_follows_sheet_order_with_prefix_constant_and_text_id():
    route = _ROUTES_TEMPLATE["routes"][1]
    headers = ["Symbol", "Notes", "Platform", "IBKR Trade ID", "", "Summary"]
    width = mapped_width(headers, route)
    row = build_row(derive_fields(dict(_fill("x1"), record_id="O1"), "now"), headers, route, width, "record_id")
    assert width == 4
    assert row == ["SGX: NVDA", "", "IBKR", "'O1"]


def test__plan_route_skips_existing_ids_and_manual_entries():
    route = _ROUTES_TEMPLATE["routes"][0]
    headers = ["Symbol", "Date", "Quantity", "Price", "Fees", "IBKR Trade ID"]
    rows = [["VT", "2026-10-15", "10", "157.06"], ["NVDA", "2026-10-16", "5", "180.4", "1", "O1"]]
    records = group_entries([
        _fill("x1"), _fill("x2", quantity=2, price=181.0),                      # O1 already synced
        _fill("x3", order_id="O2", symbol="VT", quantity=10, when="2026-10-15 22:31:00"),  # entered by hand
        _fill("x4", order_id="O3", symbol="SLV", side="SELL", quantity=-5),     # new
    ], "order")
    plan = plan_route(_FakeSheets(headers, rows), route, records, _ROUTES_TEMPLATE, "now")
    assert [r[0] for r in plan["rows"]] == ["SLV"]
    assert plan["rows"][0][2] == -5
    assert [v["symbol"] for v in plan["already_manual"]] == ["VT"]
    assert plan["new_symbols"] == ["SLV"]


def test__plan_route_requires_id_header():
    with pytest.raises(ValueError, match="prepare-sheet"):
        plan_route(_FakeSheets(["Symbol", "Date"], []), _ROUTES_TEMPLATE["routes"][0], [], _ROUTES_TEMPLATE, "now")


def test__column_letter():
    assert [column_letter(i) for i in (0, 12, 25, 26, 27)] == ["A", "M", "Z", "AA", "AB"]


# ── Deposits ──────────────────────────────────────────────────────────────────

_DEPOSITS = {
    "tab": "Top Up", "match": {"currency": "SGD"}, "insert_above_blank_row": True,
    "columns": [{"column": "A", "field": "date"}, {"header": "IBKR", "field": "amount"},
                {"header": "Notes", "field": "note"}, {"header": "IBKR Transaction ID", "field": "record_id"}],
}
_TOPUP_HEADERS = ["", "IBKR", "Other", "Notes", "IBKR Transaction ID"]
_TOPUP_ROWS = [["2026-10-07", "", "500"], ["2026-10-14", "2,500"], [], ["", "79,630"]]  # spacer, then total


def _cash(txn_id, amount=2500.0, currency="SGD", when="2026-11-11 10:00:00"):
    return {"transaction_id": txn_id, "type": "Deposits/Withdrawals", "currency": currency, "amount": amount,
            "date_time": when}


def test__plan_deposits_inserts_above_spacer_and_skips_manual_and_other_currencies():
    entries = [_cash("d1", when="2026-10-14 13:13:05"), _cash("d2"), _cash("d3", currency="USD"),
               _cash("d4", amount=-300.0, when="2026-11-12 09:00:00")]
    plan = plan_deposits(_FakeSheets(_TOPUP_HEADERS, _TOPUP_ROWS), _DEPOSITS, entries)
    assert plan["insert_index"] == 3   # 0-based: sheet row 4, the blank spacer
    assert plan["rows"] == [["2026-11-11", 2500.0, "", "IBKR deposit (auto)", "'d2"],
                            ["2026-11-12", -300.0, "", "IBKR withdrawal (auto)", "'d4"]]
    assert [v["record_id"] for v in plan["already_manual"]] == ["d1"]
    assert [v["record_id"] for v in plan["unmatched"]] == ["d3"]


def test__plan_deposits_skips_ids_already_on_the_tab():
    rows = [["2026-11-11", "2500", "", "IBKR deposit (auto)", "d2"], []]
    plan = plan_deposits(_FakeSheets(_TOPUP_HEADERS, rows), _DEPOSITS, [_cash("d2")])
    assert plan["rows"] == []


def test__letter_index():
    assert [letter_index(x) for x in ("A", "F", "Z", "AA")] == [0, 5, 25, 26]


# ── Dividends ─────────────────────────────────────────────────────────────────

def _div(txn_id, txn_type, amount, action="A1", when="2026-03-16 20:20:00", symbol="GOOGL", fx=1.28):
    return {"transaction_id": txn_id, "type": txn_type, "amount": amount, "action_id": action, "date_time": when,
            "symbol": symbol, "currency": "USD", "ex_date": "20260309" if txn_type != "Withholding Tax" else None,
            "fx_rate_to_base": fx, "description": f"{symbol} CASH DIVIDEND"}


def test__group_dividends_nets_tax_per_action_and_day():
    records = group_dividends([
        _div("t1", "Dividends", 0.63), _div("t2", "Withholding Tax", -0.19),
        _div("t3", "Withholding Tax", 0.19, when="2026-04-01 10:00:00"),       # later refund → own row
        _div("t4", "Payment In Lieu Of Dividends", 0.36, action="A2", symbol="IBKR"),
        _div("t5", "Deposits/Withdrawals", 2500.0, action=None),              # ignored
    ])
    by_id = {r["record_id"]: r for r in records}
    assert set(by_id) == {"A1-20260316", "A1-20260401", "A2-20260316"}
    first = by_id["A1-20260316"]
    assert (first["gross"], first["withholding_tax"], first["net"]) == (0.63, -0.19, 0.44)
    assert first["ex_date"] == "2026-03-09" and first["kind"] == "Dividend"
    assert first["net_base"] == round(0.44 * 1.28, 2)
    assert by_id["A1-20260401"]["kind"] == "Tax adjustment"
    assert by_id["A2-20260316"]["kind"] == "Payment in lieu"


def test__plan_dividends_new_tab_uses_template_headers_and_skips_existing():
    section = {"tab": "Dividends", "columns": [{"header": "Pay Date", "field": "pay_date"},
                                               {"header": "Net", "field": "net"},
                                               {"header": "ID", "field": "record_id"}]}
    records = group_dividends([_div("t1", "Dividends", 0.63), _div("t4", "Dividends", 1.0, action="A2")])
    plan = plan_dividends(_FakeSheets([], []), section, records, tab_exists=False)
    assert plan["headers"] == ["Pay Date", "Net", "ID"]
    assert plan["rows"] == [["2026-03-16", 0.63, "'A1-20260316"], ["2026-03-16", 1.0, "'A2-20260316"]]
    existing = _FakeSheets(["Pay Date", "Net", "ID"], [["2026-03-16", "0.63", "A1-20260316"]])
    assert [r["record_id"] for r in plan_dividends(existing, section, records)["pending"]] == ["A2-20260316"]


# ── Summary rows ──────────────────────────────────────────────────────────────

def test__adapt_formula_moves_row_local_refs_only():
    f = "=SUMIF('Buys'!A2:A9998, A2, 'Buys'!C2:C9998)"
    assert adapt_formula(f, 2, 20) == "=SUMIF('Buys'!A2:A9998, A20, 'Buys'!C2:C9998)"
    assert adapt_formula("=PRODUCT(B2:C2)", 2, 7) == "=PRODUCT(B7:C7)"
    assert adapt_formula("=SUMIF(A2:A9999, K2, C2:C9999)", 2, 3) == "=SUMIF(A2:A9999, K3, C2:C9999)"
    assert adapt_formula('=IF(B2 <= 0, "SOLD", 1)', 2, 9) == '=IF(B9 <= 0, "SOLD", 1)'
    assert adapt_formula("AAPL", 2, 9) == "AAPL"


class _FakeSummarySheets:
    """get_values for a summary block plus the FORMULA read of its pattern row."""

    def __init__(self, header, symbols, pattern, below=None):
        self.header, self.symbols, self.pattern, self.below = header, symbols, pattern, below or []
        outer = self

        class _Req:
            def __init__(self, rng): self.rng = rng
            def execute(self): return {"values": [outer.pattern]}

        class _Values:
            def get(self, spreadsheetId, range, valueRenderOption=None): return _Req(range)

        class _Spreadsheets:
            def values(self): return _Values()

        self.spreadsheets = _Spreadsheets()
        self.sheet_id = "x"

    def get_values(self, rng):
        if rng.endswith("1"):
            return [self.header]
        if rng.endswith(":A") or rng.endswith(":K"):
            return [[s] for s in self.symbols]
        return self.below


def test__plan_summary_adds_missing_symbols_from_row_2_pattern():
    sheets = _FakeSummarySheets(["Symbol", "Qty", "Total"], ["AAPL", "VT"],
                                ["AAPL", "=SUMIF('Buys'!A2:A99, A2, 'Buys'!C2:C99)", "=PRODUCT(B2:B2)"])
    plan = plan_summary(sheets, {"tab": "Summary", "symbol_column": "A"}, ["VT", "AMZN", "amzn"])
    assert plan["symbols"] == ["AMZN"]
    assert plan["rows"] == [{"row": 4, "range": "'Summary'!A4:C4",
                             "values": ["AMZN", "=SUMIF('Buys'!A2:A99, A4, 'Buys'!C2:C99)", "=PRODUCT(B4:B4)"]}]


def test__plan_summary_refuses_to_overwrite():
    sheets = _FakeSummarySheets(["Symbol", "Qty"], ["AAPL"], ["AAPL", "=1"], below=[["", "something"]])
    with pytest.raises(ValueError, match="not empty"):
        plan_summary(sheets, {"tab": "Summary", "symbol_column": "A"}, ["AMZN"])
