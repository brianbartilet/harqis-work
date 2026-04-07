import logging

from mcp.server.fastmcp import FastMCP
from apps.oanda.config import CONFIG
from apps.oanda.references.web.api.account import ApiServiceOandaAccount
from apps.oanda.references.web.api.open_trades import ApiServiceTrades
from apps.oanda.references.web.api.pricing import ApiServiceOandaPricing
from apps.oanda.references.web.api.orders import ApiServiceOandaOrders
from apps.oanda.references.web.api.positions import ApiServiceOandaPositions
from apps.oanda.references.web.api.transactions import ApiServiceOandaTransactions
from apps.oanda.references.web.api.instruments import ApiServiceOandaInstruments

logger = logging.getLogger("harqis-mcp.oanda")


def register_oanda_tools(mcp: FastMCP):

    # ── Account ───────────────────────────────────────────────────────────

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
    def get_oanda_account_summary(account_id: str) -> dict:
        """Get lightweight account summary for a specific OANDA account.

        Args:
            account_id: The OANDA account ID
        """
        logger.info("Tool called: get_oanda_account_summary account_id=%s", account_id)
        service = ApiServiceOandaAccount(CONFIG)
        result = service.get_account_summary(account_id)
        return result if isinstance(result, dict) else {}

    # ── Trades ────────────────────────────────────────────────────────────

    @mcp.tool()
    def get_oanda_open_trades(account_id: str) -> list[dict]:
        """Get all currently open trades for a specific OANDA account.

        Args:
            account_id: The OANDA account ID
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

    @mcp.tool()
    def get_oanda_trade(account_id: str, trade_specifier: str) -> dict:
        """Get details of a specific OANDA trade.

        Args:
            account_id: The OANDA account ID
            trade_specifier: Trade ID (or '@clientTradeID' for client IDs)
        """
        logger.info("Tool called: get_oanda_trade account_id=%s trade=%s", account_id, trade_specifier)
        service = ApiServiceTrades(CONFIG)
        result = service.get_trade(account_id, trade_specifier)
        return result if isinstance(result, dict) else {}

    # ── Pricing ───────────────────────────────────────────────────────────

    @mcp.tool()
    def get_oanda_prices(account_id: str, instruments: str) -> dict:
        """Get current bid/ask prices for one or more instruments.

        Args:
            account_id: The OANDA account ID
            instruments: Comma-separated instrument list (e.g. 'EUR_USD,USD_JPY,GBP_USD')
        """
        logger.info("Tool called: get_oanda_prices account_id=%s instruments=%s", account_id, instruments)
        service = ApiServiceOandaPricing(CONFIG)
        result = service.get_prices(account_id, instruments)
        return result if isinstance(result, dict) else {}

    @mcp.tool()
    def get_oanda_candles(account_id: str, instrument: str,
                          granularity: str = 'H1', count: int = 100) -> dict:
        """Get OHLC candlestick data for an instrument (account-scoped).

        Args:
            account_id: The OANDA account ID
            instrument: Instrument name (e.g. 'EUR_USD')
            granularity: Candle size — S5, S10, S15, S30, M1, M2, M4, M5, M10, M15, M30,
                         H1, H2, H3, H4, H6, H8, H12, D, W, M. Default H1.
            count: Number of candles to return (max 5000). Default 100.
        """
        logger.info("Tool called: get_oanda_candles instrument=%s granularity=%s count=%d",
                    instrument, granularity, count)
        service = ApiServiceOandaPricing(CONFIG)
        result = service.get_instrument_candles(account_id, instrument, granularity=granularity, count=count)
        return result if isinstance(result, dict) else {}

    # ── Instruments (non-account-scoped) ─────────────────────────────────

    @mcp.tool()
    def get_oanda_instrument_candles(instrument: str, granularity: str = 'H1',
                                     count: int = 100) -> dict:
        """Get OHLC candlestick data for an instrument (no account required).

        Args:
            instrument: Instrument name (e.g. 'EUR_USD')
            granularity: Candle size — S5, M1, M5, M15, M30, H1, H4, D, W, M. Default H1.
            count: Number of candles to return (max 5000). Default 100.
        """
        logger.info("Tool called: get_oanda_instrument_candles instrument=%s granularity=%s count=%d",
                    instrument, granularity, count)
        service = ApiServiceOandaInstruments(CONFIG)
        result = service.get_candles(instrument, granularity=granularity, count=count)
        return result if isinstance(result, dict) else {}

    @mcp.tool()
    def get_oanda_order_book(instrument: str) -> dict:
        """Get the order book snapshot for an instrument showing aggregated orders at price levels.

        Args:
            instrument: Instrument name (e.g. 'EUR_USD')
        """
        logger.info("Tool called: get_oanda_order_book instrument=%s", instrument)
        service = ApiServiceOandaInstruments(CONFIG)
        result = service.get_order_book(instrument)
        return result if isinstance(result, dict) else {}

    @mcp.tool()
    def get_oanda_position_book(instrument: str) -> dict:
        """Get the position book snapshot for an instrument showing aggregated positions at price levels.

        Args:
            instrument: Instrument name (e.g. 'EUR_USD')
        """
        logger.info("Tool called: get_oanda_position_book instrument=%s", instrument)
        service = ApiServiceOandaInstruments(CONFIG)
        result = service.get_position_book(instrument)
        return result if isinstance(result, dict) else {}

    # ── Orders ────────────────────────────────────────────────────────────

    @mcp.tool()
    def get_oanda_orders(account_id: str, instrument: str = None,
                         state: str = None, count: int = 50) -> list[dict]:
        """Get orders for a specific OANDA account.

        Args:
            account_id: The OANDA account ID
            instrument: Filter by instrument (e.g. 'EUR_USD')
            state: Filter by state — PENDING, FILLED, TRIGGERED, CANCELLED, ALL
            count: Max orders to return (default 50)
        """
        logger.info("Tool called: get_oanda_orders account_id=%s instrument=%s", account_id, instrument)
        service = ApiServiceOandaOrders(CONFIG)
        result = service.get_orders(account_id, instrument=instrument, state=state, count=count)
        return result if isinstance(result, list) else []

    @mcp.tool()
    def get_oanda_pending_orders(account_id: str) -> list[dict]:
        """Get all pending orders for a specific OANDA account.

        Args:
            account_id: The OANDA account ID
        """
        logger.info("Tool called: get_oanda_pending_orders account_id=%s", account_id)
        service = ApiServiceOandaOrders(CONFIG)
        result = service.get_pending_orders(account_id)
        return result if isinstance(result, list) else []

    # ── Positions ─────────────────────────────────────────────────────────

    @mcp.tool()
    def get_oanda_positions(account_id: str) -> list[dict]:
        """Get all positions (including closed) for a specific OANDA account.

        Args:
            account_id: The OANDA account ID
        """
        logger.info("Tool called: get_oanda_positions account_id=%s", account_id)
        service = ApiServiceOandaPositions(CONFIG)
        result = service.get_positions(account_id)
        return result if isinstance(result, list) else []

    @mcp.tool()
    def get_oanda_open_positions(account_id: str) -> list[dict]:
        """Get all currently open positions for a specific OANDA account.

        Args:
            account_id: The OANDA account ID
        """
        logger.info("Tool called: get_oanda_open_positions account_id=%s", account_id)
        service = ApiServiceOandaPositions(CONFIG)
        result = service.get_open_positions(account_id)
        return result if isinstance(result, list) else []

    # ── Transactions ──────────────────────────────────────────────────────

    @mcp.tool()
    def get_oanda_transactions(account_id: str, page_size: int = 100) -> dict:
        """Get transaction history pages for a specific OANDA account.

        Args:
            account_id: The OANDA account ID
            page_size: Transactions per page (default 100, max 1000)
        """
        logger.info("Tool called: get_oanda_transactions account_id=%s", account_id)
        service = ApiServiceOandaTransactions(CONFIG)
        result = service.get_transactions(account_id, page_size=page_size)
        return result if isinstance(result, dict) else {}

    @mcp.tool()
    def get_oanda_transaction(account_id: str, transaction_id: str) -> dict:
        """Get details of a specific OANDA transaction.

        Args:
            account_id: The OANDA account ID
            transaction_id: Transaction ID
        """
        logger.info("Tool called: get_oanda_transaction account_id=%s transaction_id=%s",
                    account_id, transaction_id)
        service = ApiServiceOandaTransactions(CONFIG)
        result = service.get_transaction(account_id, transaction_id)
        return result if isinstance(result, dict) else {}
