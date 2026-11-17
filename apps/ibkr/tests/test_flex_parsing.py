"""Offline tests for the Flex XML parsing and GetStatement retry handling (no credentials)."""
from datetime import datetime

import pytest
from hamcrest import assert_that, equal_to, has_length, none

from apps.ibkr.config import CONFIG
from apps.ibkr.references.web.api.flex import (
    ApiServiceIbkrFlex, IbkrFlexError, parse_cash_transactions, parse_flex_datetime, parse_trades,
)

TRADE_CONFIRM_XML = """<FlexQueryResponse queryName="trades" type="TCF">
<FlexStatements count="1"><FlexStatement accountId="U0000000">
<TradeConfirms>
  <TradeConfirm accountId="U0000000" currency="USD" assetCategory="STK" symbol="AAPL"
    description="APPLE INC" execID="0000e0d5.1" tradeID="111" buySell="BUY" quantity="10"
    price="230.5" amount="2305" commission="-1" commissionCurrency="USD" exchange="NASDAQ"
    orderType="LMT" dateTime="20261016;101500" levelOfDetail="EXECUTION" />
  <TradeConfirm accountId="U0000000" currency="USD" assetCategory="OPT" symbol="AAPL 261120C00250000"
    execID="0000e0d5.2" buySell="BUY" quantity="1" price="3.1" dateTime="20261016;101600" />
  <TradeConfirm accountId="U0000000" currency="USD" assetCategory="STK" symbol="MSFT"
    execID="0000e0d5.3" buySell="SELL" quantity="-5" price="410" dateTime="2026-10-15;15:59:00" />
</TradeConfirms></FlexStatement></FlexStatements></FlexQueryResponse>"""

ACTIVITY_XML = """<FlexQueryResponse><FlexStatements><FlexStatement><Trades>
  <Trade assetCategory="STK" symbol="NVDA" tradeID="900" buySell="BUY" quantity="2"
    tradePrice="120" ibCommission="-0.35" ibCommissionCurrency="USD" tradeDate="20261016"
    tradeTime="093000" levelOfDetail="EXECUTION" />
  <Trade assetCategory="STK" symbol="NVDA" tradeID="901" levelOfDetail="ORDER" />
</Trades></FlexStatement></FlexStatements></FlexQueryResponse>"""

SEND_OK = ("<FlexStatementResponse><Status>Success</Status>"
           "<ReferenceCode>REF1</ReferenceCode></FlexStatementResponse>")
IN_PROGRESS = ("<FlexStatementResponse><Status>Warn</Status><ErrorCode>1019</ErrorCode>"
               "<ErrorMessage>Statement generation in progress.</ErrorMessage></FlexStatementResponse>")
TOO_MANY = ("<FlexStatementResponse><Status>Fail</Status><ErrorCode>1018</ErrorCode>"
            "<ErrorMessage>Too many requests have been made from this token.</ErrorMessage></FlexStatementResponse>")
BAD_TOKEN = ("<FlexStatementResponse><Status>Fail</Status><ErrorCode>1020</ErrorCode>"
             "<ErrorMessage>Invalid request or unable to validate request.</ErrorMessage></FlexStatementResponse>")


class _ScriptedFlex(ApiServiceIbkrFlex):
    """ApiServiceIbkrFlex with flex_get replaced by scripted XML responses."""

    def __init__(self, bodies):
        super().__init__(CONFIG, flex_token='token', query_id='Q1', sleep=lambda seconds: None)
        self.bodies = list(bodies)
        self.calls = []
        self.params = []

    def flex_get(self, endpoint, q, **params):
        self.calls.append((endpoint, q))
        self.params.append(params)
        return self.bodies.pop(0)


def test_parse_trades_trade_confirms():
    when = parse_trades(TRADE_CONFIRM_XML)
    assert_that([t.symbol for t in when], equal_to(["AAPL", "AAPL 261120C00250000", "MSFT"]))
    aapl = when[0]
    assert_that(aapl.trade_id, equal_to("111"))
    assert_that((aapl.side, aapl.quantity, aapl.price, aapl.commission), equal_to(("BUY", 10.0, 230.5, -1.0)))
    assert_that(aapl.trade_time, equal_to(datetime(2026, 10, 16, 10, 15)))
    assert_that(when[2].trade_time, equal_to(datetime(2026, 10, 15, 15, 59)))


def test_parse_trades_activity_aliases_and_skips_order_rows():
    when = parse_trades(ACTIVITY_XML)
    assert_that(when, has_length(1))
    assert_that((when[0].trade_id, when[0].price, when[0].commission), equal_to(("900", 120.0, -0.35)))
    assert_that(when[0].trade_time, equal_to(datetime(2026, 10, 16, 9, 30)))


def test_parse_flex_datetime_variants():
    assert_that(parse_flex_datetime("20261016"), equal_to(datetime(2026, 10, 16)))
    assert_that(parse_flex_datetime("2026-10-16 09:35:12"), equal_to(datetime(2026, 10, 16, 9, 35, 12)))
    assert_that(parse_flex_datetime(""), none())


def test_get_statement_retries_while_generating():
    given = _ScriptedFlex([SEND_OK, IN_PROGRESS, TRADE_CONFIRM_XML])
    when = given.get_trades()
    assert_that(when, has_length(3))
    assert_that(given.calls, equal_to([("SendRequest", "Q1"), ("GetStatement", "REF1"), ("GetStatement", "REF1")]))


def test_send_request_retries_when_paced():
    given = _ScriptedFlex([TOO_MANY, SEND_OK, TRADE_CONFIRM_XML])
    when = given.get_trades()
    assert_that(when, has_length(3))
    assert_that(given.calls, equal_to([("SendRequest", "Q1"), ("SendRequest", "Q1"), ("GetStatement", "REF1")]))


def test_send_request_raises_on_invalid_token():
    given = _ScriptedFlex([BAD_TOKEN])
    with pytest.raises(IbkrFlexError, match="1020"):
        given.get_trades()


CASH_XML = """<FlexQueryResponse><FlexStatements><FlexStatement><CashTransactions>
  <CashTransaction currency="SGD" type="Deposits/Withdrawals" amount="2500" dateTime="20261014;131305"
    transactionID="900001" description="CASH RECEIPTS / ELECTRONIC FUND TRANSFERS" levelOfDetail="DETAIL" />
  <CashTransaction currency="SGD" type="Deposits/Withdrawals" amount="2500" levelOfDetail="SUMMARY" />
  <CashTransaction currency="USD" type="Dividends" amount="1.23" dateTime="20261015" transactionID="900002" />
</CashTransactions></FlexStatement></FlexStatements></FlexQueryResponse>"""


def test_parse_cash_transactions_keeps_detail_rows():
    when = parse_cash_transactions(CASH_XML)
    assert_that([t.transaction_id for t in when], equal_to(["900001", "900002"]))
    assert_that((when[0].type, when[0].currency, when[0].amount), equal_to(("Deposits/Withdrawals", "SGD", 2500.0)))
    assert_that(when[0].date_time, equal_to(datetime(2026, 10, 14, 13, 13, 5)))


def test_get_trades_date_range_is_chunked_by_365_days():
    given = _ScriptedFlex([SEND_OK, TRADE_CONFIRM_XML, SEND_OK, ACTIVITY_XML])
    when = given.get_trades(from_date="20250101", to_date="20261016")
    assert_that(when, has_length(4))
    sends = [p for (endpoint, _), p in zip(given.calls, given.params) if endpoint == "SendRequest"]
    assert_that(sends, equal_to([{"fd": "20250101", "td": "20251231"}, {"fd": "20260101", "td": "20261016"}]))
