import logging
from datetime import date, datetime, timedelta
from typing import Optional

from mcp.server.fastmcp import FastMCP
from apps.ibkr.config import CONFIG
from apps.ibkr.references.web.api.flex import ApiServiceIbkrFlex

logger = logging.getLogger("harqis-mcp.ibkr")


def _flex_date(value: Optional[str]) -> Optional[str]:
    """Accept 'YYYY-MM-DD' or 'YYYYMMDD'; return the Flex 'YYYYMMDD' form."""
    if not value:
        return None
    digits = value.replace("-", "").strip()
    datetime.strptime(digits, "%Y%m%d")  # raises ValueError on a bad date
    return digits


def _flex_range(from_date: Optional[str], to_date: Optional[str], latest: date) -> tuple:
    """(fd, td) for a requested range; to_date defaults to and is capped at ``latest``."""
    fd = _flex_date(from_date)
    if not fd:
        return None, None
    td = min(_flex_date(to_date) or latest.strftime("%Y%m%d"), latest.strftime("%Y%m%d"))
    if td < fd:
        raise ValueError(f"to_date {td} is before from_date {fd}")
    return fd, td


def register_ibkr_tools(mcp: FastMCP):

    # ── Flex reports (read-only) ──────────────────────────────────────────

    @mcp.tool()
    def get_ibkr_trades(asset_category: Optional[str] = None, from_date: Optional[str] = None,
                        to_date: Optional[str] = None, query_id: Optional[str] = None) -> list[dict]:
        """Get executed Interactive Brokers trades from a saved Flex Query report (read-only).

        Without dates it returns the query's saved period (today's fills for the Trade
        Confirmation query). Pass from_date to fetch any historical range instead, e.g.
        from_date='2026-09-01' for "since last month"; ranges over 365 days are fetched in
        chunks. Takes a few seconds per request while IBKR generates the report.

        Args:
            asset_category: Optional filter, e.g. 'STK' (stocks), 'OPT' (options), 'FUT', 'CASH'.
            from_date:      Optional start date 'YYYY-MM-DD' (inclusive); overrides the saved period.
            to_date:        Optional end date 'YYYY-MM-DD' (inclusive); defaults to today.
            query_id:       Optional Flex Query ID; defaults to IBKR_FLEX_QUERY_ID_TRADES.
        """
        logger.info("Tool called: get_ibkr_trades asset_category=%s from_date=%s to_date=%s query_id=%s",
                    asset_category, from_date, to_date, query_id)
        fd, td = _flex_range(from_date, to_date, date.today())
        service = ApiServiceIbkrFlex(CONFIG)
        trades = service.get_trades(query_id, fd, td)
        if asset_category:
            trades = [t for t in trades if (t.asset_category or "").upper() == asset_category.upper()]
        result = []
        for t in trades:
            row = dict(t.__dict__)
            row["trade_time"] = t.trade_time.isoformat() if t.trade_time else None
            result.append(row)
        logger.info("get_ibkr_trades returned %d trade(s)", len(result))
        return result

    @mcp.tool()
    def get_ibkr_cash_transactions(transaction_type: Optional[str] = None, from_date: Optional[str] = None,
                                   to_date: Optional[str] = None, query_id: Optional[str] = None) -> list[dict]:
        """Get Interactive Brokers cash transactions (deposits, withdrawals, dividends, ...) from the
        Activity Flex Query report (read-only).

        Without dates it returns the query's saved period (e.g. the last 7 days). Pass from_date
        for any historical range; the Activity report only covers processed days, so the range
        ends yesterday at the latest.

        Args:
            transaction_type: Optional filter, e.g. 'Deposits/Withdrawals' or 'Dividends'.
            from_date:        Optional start date 'YYYY-MM-DD' (inclusive); overrides the saved period.
            to_date:          Optional end date 'YYYY-MM-DD' (inclusive); defaults to (and is capped at) yesterday.
            query_id:         Optional Flex Query ID; defaults to IBKR_FLEX_QUERY_ID_ACTIVITY.
        """
        logger.info("Tool called: get_ibkr_cash_transactions transaction_type=%s from_date=%s to_date=%s query_id=%s",
                    transaction_type, from_date, to_date, query_id)
        fd, td = _flex_range(from_date, to_date, date.today() - timedelta(days=1))
        service = ApiServiceIbkrFlex(CONFIG)
        transactions = service.get_cash_transactions(query_id or CONFIG.app_data.get("flex_query_id_activity"), fd, td)
        if transaction_type:
            transactions = [t for t in transactions if (t.type or "").lower() == transaction_type.lower()]
        result = []
        for t in transactions:
            row = dict(t.__dict__)
            row["date_time"] = t.date_time.isoformat() if t.date_time else None
            result.append(row)
        logger.info("get_ibkr_cash_transactions returned %d transaction(s)", len(result))
        return result
