"""
IBKR Flex Web Service — report generation and trade parsing.

Flow:
  1. SendRequest?t=<token>&q=<query_id>&v=3   -> ReferenceCode
  2. GetStatement?t=<token>&q=<reference>&v=3 -> statement XML
     (retry while the statement is still being generated, ErrorCode 1019).
"""
import re
import time
import xml.etree.ElementTree as ET
from datetime import date, datetime, timedelta
from typing import Dict, List, Optional

from apps.ibkr.references.dto.trade import DtoIbkrCashTransaction, DtoIbkrTrade
from apps.ibkr.references.web.base_api_service import BaseApiServiceIbkr

# Codes IBKR documents as temporary (server busy / statement not ready yet).
RETRYABLE_ERROR_CODES = {'1001', '1004', '1009', '1019'}
MAX_RANGE_DAYS = 365  # IBKR serves at most 365 days per Flex request
PACING_ERROR_CODE = '1018'  # too many requests for this token (SendRequest: 1/second, 10/minute)

# Flex attribute names differ between Trade Confirmation (<TradeConfirm>) and
# Activity (<Trade>) queries, so each field lists its accepted aliases.
_ALIASES = {
    # tradeID is present in both Trade Confirmation and Activity reports, so it is the
    # stable key across query types; execution IDs differ in name between the two.
    'trade_id': ('tradeID', 'execID', 'ibExecID', 'transactionID'),
    'price': ('price', 'tradePrice'),
    'amount': ('amount', 'tradeMoney', 'proceeds'),
    'commission': ('commission', 'ibCommission'),
    'commission_currency': ('commissionCurrency', 'ibCommissionCurrency'),
}


class IbkrFlexError(RuntimeError):
    def __init__(self, code: str, message: str):
        super().__init__(f"IBKR Flex error {code}: {message}")
        self.code = code


class ApiServiceIbkrFlex(BaseApiServiceIbkr):

    def __init__(self, config, **kwargs):
        super(ApiServiceIbkrFlex, self).__init__(config, **kwargs)
        self.default_query_id = kwargs.get('query_id', config.app_data.get('flex_query_id_trades'))
        self._sleep = kwargs.get('sleep', time.sleep)

    def send_request(self, query_id: str, from_date: Optional[str] = None, to_date: Optional[str] = None,
                     attempts: int = 3, wait_seconds: float = 10) -> str:
        """Ask IBKR to generate a saved Flex Query; returns the reference code.

        ``from_date`` / ``to_date`` (YYYYMMDD) override the query's saved period
        (``fd`` / ``td``); IBKR serves at most 365 days per request and only days
        it has already processed (error 1003 otherwise). Pacing rejections (1018)
        are retried after ``wait_seconds``.
        """
        for attempt in range(attempts):
            status = parse_flex_status(self.flex_get('SendRequest', query_id, fd=from_date, td=to_date))
            if status is None:
                raise IbkrFlexError('parse', 'SendRequest did not return a FlexStatementResponse')
            state, code, message, reference = status
            if state == 'Success' and reference:
                return reference
            if code != PACING_ERROR_CODE or attempt == attempts - 1:
                raise IbkrFlexError(code or state, message or 'SendRequest failed')
            self._sleep(wait_seconds)
        raise IbkrFlexError('timeout', 'SendRequest was not accepted in time')

    def get_statement(self, reference: str, attempts: int = 10, wait_seconds: float = 5) -> str:
        """Download a generated statement, waiting while IBKR is still building it."""
        for attempt in range(attempts):
            body = self.flex_get('GetStatement', reference)
            status = parse_flex_status(body)
            if status is None:
                return body  # the statement itself (FlexQueryResponse)
            _, code, message, _ = status
            if code not in RETRYABLE_ERROR_CODES or attempt == attempts - 1:
                raise IbkrFlexError(code, message)
            self._sleep(wait_seconds)
        raise IbkrFlexError('timeout', 'Statement was not ready in time')

    def get_statement_for_query(self, query_id: Optional[str] = None, from_date: Optional[str] = None,
                                to_date: Optional[str] = None) -> str:
        """Generate and download a Flex Query report (XML), optionally for a date range (YYYYMMDD)."""
        reference = self.send_request(query_id or self.default_query_id, from_date, to_date)
        self._sleep(2)  # give IBKR a moment to build it; also respects pacing
        return self.get_statement(reference)

    def get_statements_for_range(self, query_id: Optional[str], from_date: str, to_date: str) -> List[str]:
        """Download a Flex Query for any YYYYMMDD range, one statement per <= 365-day chunk."""
        start, end = datetime.strptime(from_date, '%Y%m%d').date(), datetime.strptime(to_date, '%Y%m%d').date()
        statements = []
        for index, (fd, td) in enumerate(date_ranges(start, end)):
            if index:
                self._sleep(2)  # SendRequest pacing
            statements.append(self.get_statement_for_query(query_id, fd, td))
        return statements

    def _statements(self, query_id: Optional[str], from_date: Optional[str], to_date: Optional[str]) -> List[str]:
        if from_date and to_date:
            return self.get_statements_for_range(query_id, from_date, to_date)
        return [self.get_statement_for_query(query_id, from_date, to_date)]

    def get_trades(self, query_id: Optional[str] = None, from_date: Optional[str] = None,
                   to_date: Optional[str] = None) -> List[DtoIbkrTrade]:
        """Return every execution in the Flex Query report (defaults to the trades query).

        ``from_date`` / ``to_date`` (YYYYMMDD) replace the query's saved period; ranges longer
        than 365 days are fetched in chunks.
        """
        return [trade for statement in self._statements(query_id, from_date, to_date)
                for trade in parse_trades(statement)]

    def get_cash_transactions(self, query_id: Optional[str] = None, from_date: Optional[str] = None,
                              to_date: Optional[str] = None) -> List[DtoIbkrCashTransaction]:
        """Return the cash transactions (deposits, withdrawals, ...) in an Activity Flex Query report.

        ``from_date`` / ``to_date`` (YYYYMMDD) as for ``get_trades``; Activity queries only serve
        processed days, so ``to_date`` must be yesterday or earlier.
        """
        return [cash for statement in self._statements(query_id, from_date, to_date)
                for cash in parse_cash_transactions(statement)]


def date_ranges(start: date, end: date, max_days: int = MAX_RANGE_DAYS) -> List[tuple]:
    """Split [start, end] into consecutive (YYYYMMDD, YYYYMMDD) chunks of at most max_days."""
    ranges = []
    while start <= end:
        chunk_end = min(end, start + timedelta(days=max_days - 1))
        ranges.append((start.strftime('%Y%m%d'), chunk_end.strftime('%Y%m%d')))
        start = chunk_end + timedelta(days=1)
    return ranges


def parse_flex_status(xml_text: str):
    """Return (status, code, message, reference) for a FlexStatementResponse, else None."""
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError as e:
        raise IbkrFlexError('parse', f"Unexpected non-XML response: {xml_text[:200]!r}") from e
    if root.tag != 'FlexStatementResponse':
        return None
    return (
        (root.findtext('Status') or '').strip(),
        (root.findtext('ErrorCode') or '').strip(),
        (root.findtext('ErrorMessage') or '').strip(),
        (root.findtext('ReferenceCode') or '').strip(),
    )


def parse_flex_datetime(value: str) -> Optional[datetime]:
    """Parse Flex date/time values regardless of the query's separators.

    Accepts e.g. '20261016;093512', '2026-10-16;09:35:12', '2026-10-16 09:35:12'
    or a bare date '20261016'.
    """
    digits = re.sub(r'\D', '', value or '')
    try:
        if len(digits) >= 14:
            return datetime.strptime(digits[:14], '%Y%m%d%H%M%S')
        if len(digits) == 8:
            return datetime.strptime(digits, '%Y%m%d')
    except ValueError:
        return None
    return None


def _first(attrs: Dict[str, str], *names: str) -> str:
    for name in names:
        value = attrs.get(name)
        if value not in (None, ''):
            return value
    return ''


def _to_float(value: str) -> Optional[float]:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def to_trade(attrs: Dict[str, str]) -> DtoIbkrTrade:
    when = parse_flex_datetime(_first(attrs, 'dateTime')) \
        or parse_flex_datetime(f"{_first(attrs, 'tradeDate')};{_first(attrs, 'tradeTime')}") \
        or parse_flex_datetime(_first(attrs, 'tradeDate'))
    return DtoIbkrTrade(
        trade_id=_first(attrs, *_ALIASES['trade_id']) or None,
        account_id=_first(attrs, 'accountId') or None,
        symbol=_first(attrs, 'symbol') or None,
        description=_first(attrs, 'description') or None,
        asset_category=_first(attrs, 'assetCategory') or None,
        side=_first(attrs, 'buySell').upper() or None,
        quantity=_to_float(_first(attrs, 'quantity')),
        price=_to_float(_first(attrs, *_ALIASES['price'])),
        currency=_first(attrs, 'currency') or None,
        amount=_to_float(_first(attrs, *_ALIASES['amount'])),
        commission=_to_float(_first(attrs, *_ALIASES['commission'])),
        commission_currency=_first(attrs, *_ALIASES['commission_currency']) or None,
        exchange=_first(attrs, 'exchange') or None,
        order_type=_first(attrs, 'orderType') or None,
        order_id=_first(attrs, 'ibOrderID', 'orderID') or None,
        listing_exchange=_first(attrs, 'listingExchange') or None,
        sub_category=_first(attrs, 'subCategory') or None,
        trade_time=when,
    )


def parse_trades(statement_xml: str) -> List[DtoIbkrTrade]:
    """Every execution row (<TradeConfirm> or execution-level <Trade>) in a Flex statement."""
    root = ET.fromstring(statement_xml)
    trades = []
    for element in root.iter():
        if element.tag not in ('TradeConfirm', 'Trade'):
            continue
        # Activity statements can include ORDER / CLOSED_LOT summary rows; keep executions only.
        if element.attrib.get('levelOfDetail', 'EXECUTION').upper() != 'EXECUTION':
            continue
        trades.append(to_trade(dict(element.attrib)))
    return trades


def to_cash_transaction(attrs: Dict[str, str]) -> DtoIbkrCashTransaction:
    return DtoIbkrCashTransaction(
        transaction_id=_first(attrs, 'transactionID') or None,
        account_id=_first(attrs, 'accountId') or None,
        type=_first(attrs, 'type') or None,
        symbol=_first(attrs, 'symbol') or None,
        action_id=_first(attrs, 'actionID') or None,
        ex_date=_first(attrs, 'exDate') or None,
        description=_first(attrs, 'description') or None,
        currency=_first(attrs, 'currency') or None,
        amount=_to_float(_first(attrs, 'amount')),
        fx_rate_to_base=_to_float(_first(attrs, 'fxRateToBase')),
        date_time=parse_flex_datetime(_first(attrs, 'dateTime', 'reportDate')),
        settle_date=_first(attrs, 'settleDate') or None,
    )


def parse_cash_transactions(statement_xml: str) -> List[DtoIbkrCashTransaction]:
    """Every detail-level <CashTransaction> in a Flex statement (summary rows are skipped)."""
    root = ET.fromstring(statement_xml)
    return [
        to_cash_transaction(dict(element.attrib))
        for element in root.iter('CashTransaction')
        if element.attrib.get('levelOfDetail', 'DETAIL').upper() == 'DETAIL'
    ]
