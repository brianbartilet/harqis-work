import logging

from mcp.server.fastmcp import FastMCP
from apps.oanda.config import CONFIG
from apps.oanda.references.web.api.account import ApiServiceOandaAccount
from apps.oanda.references.web.api.open_trades import ApiServiceTrades

logger = logging.getLogger("harqis-mcp.oanda")


def register_oanda_tools(mcp: FastMCP):

    @mcp.tool()
    def get_oanda_accounts() -> list[dict]:
        """Get all OANDA accounts for the configured user."""
        logger.info("Tool called: get_oanda_accounts")
        service = ApiServiceOandaAccount(CONFIG)
        accounts = service.get_account_info()
        result = [{"id": a.id, "mt4AccountID": a.mt4AccountID, "tags": a.tags} for a in accounts]
        logger.info("get_oanda_accounts returned %d account(s)", len(result))
        return result

    @mcp.tool()
    def get_oanda_account_details(account_id: str) -> dict:
        """Get detailed information for a specific OANDA account including balance, NAV, and open positions.

        Args:
            account_id: The OANDA account ID (e.g. '001-011-1234567-001')
        """
        logger.info("Tool called: get_oanda_account_details account_id=%s", account_id)
        service = ApiServiceOandaAccount(CONFIG)
        details = service.get_account_details(account_id)
        result = {
            "id": details.id,
            "alias": details.alias,
            "currency": details.currency,
            "balance": details.balance,
            "NAV": details.NAV,
            "marginRate": details.marginRate,
            "openTradeCount": details.openTradeCount,
            "openPositionCount": details.openPositionCount,
            "pendingOrderCount": details.pendingOrderCount,
        }
        logger.info("get_oanda_account_details balance=%s currency=%s", details.balance, details.currency)
        return result

    @mcp.tool()
    def get_oanda_open_trades(account_id: str) -> list[dict]:
        """Get all currently open trades for a specific OANDA account.

        Args:
            account_id: The OANDA account ID (e.g. '001-011-1234567-001')
        """
        logger.info("Tool called: get_oanda_open_trades account_id=%s", account_id)
        service = ApiServiceTrades(CONFIG)
        trades = service.get_open_trades_from_account(account_id)
        result = trades if isinstance(trades, list) else []
        logger.info("get_oanda_open_trades returned %d open trade(s)", len(result))
        return result

    @mcp.tool()
    def get_oanda_trades(account_id: str, instrument: str = None, count: int = 50) -> list[dict]:
        """Get trade history for a specific OANDA account with optional filters.

        Args:
            account_id: The OANDA account ID
            instrument: Optional currency pair filter (e.g. 'EUR_USD')
            count: Number of trades to return (default 50)
        """
        logger.info("Tool called: get_oanda_trades account_id=%s instrument=%s count=%d", account_id, instrument, count)
        service = ApiServiceTrades(CONFIG)
        kwargs = {"count": count}
        if instrument:
            kwargs["instrument"] = instrument
        trades = service.get_trades_from_account(account_id, **kwargs)
        result = trades if isinstance(trades, list) else []
        logger.info("get_oanda_trades returned %d trade(s)", len(result))
        return result
