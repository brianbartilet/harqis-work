"""
MCP tools for Alpha Vantage.

API reference: https://www.alphavantage.co/documentation/
Base URL: https://www.alphavantage.co/query — auth via `apikey` query param.

Each tool is a thin wrapper over a category service in
`apps/alpha_vantage/references/web/api/`. To expose a new endpoint, follow the
docs URL above, add the method to the matching service class, then add a
@mcp.tool() wrapper here.
"""
import logging

from mcp.server.fastmcp import FastMCP
from apps.alpha_vantage.config import CONFIG
from apps.alpha_vantage.references.web.api.core_stock import ApiServiceAlphaVantageCoreStock
from apps.alpha_vantage.references.web.api.fx import ApiServiceAlphaVantageFx
from apps.alpha_vantage.references.web.api.news import ApiServiceAlphaVantageNews
from apps.alpha_vantage.references.web.api.fundamentals import ApiServiceAlphaVantageFundamentals
from apps.alpha_vantage.references.web.api.technicals import ApiServiceAlphaVantageTechnicals
from apps.alpha_vantage.references.web.api.crypto import ApiServiceAlphaVantageCrypto
from apps.alpha_vantage.references.web.api.commodities import ApiServiceAlphaVantageCommodities
from apps.alpha_vantage.references.web.api.economic import ApiServiceAlphaVantageEconomic

logger = logging.getLogger("harqis-mcp.alpha_vantage")


def _as_dict(result) -> dict:
    return result if isinstance(result, dict) else {}


def register_alpha_vantage_tools(mcp: FastMCP):

    # ── Core Stock ─────────────────────────────────────────────────────────

    @mcp.tool()
    def alpha_vantage_global_quote(symbol: str) -> dict:
        """Get the latest quote (price, volume, daily change) for a single ticker.

        Args:
            symbol: Equity ticker (e.g. 'IBM', 'AAPL', 'TSLA').
        """
        logger.info("Tool called: alpha_vantage_global_quote symbol=%s", symbol)
        result = ApiServiceAlphaVantageCoreStock(CONFIG).get_global_quote(symbol)
        return _as_dict(result)

    @mcp.tool()
    def alpha_vantage_realtime_bulk_quotes(symbols: str) -> dict:
        """Get realtime quotes for up to 100 US-traded symbols in one call.

        Args:
            symbols: Comma-separated tickers (e.g. 'IBM,AAPL,MSFT').
        """
        logger.info("Tool called: alpha_vantage_realtime_bulk_quotes symbols=%s", symbols)
        result = ApiServiceAlphaVantageCoreStock(CONFIG).get_realtime_bulk_quotes(symbols)
        return _as_dict(result)

    @mcp.tool()
    def alpha_vantage_search_symbol(keywords: str) -> dict:
        """Search for symbols by company name or keyword. Returns best matches with scores.

        Args:
            keywords: Search text (e.g. 'tesla', 'microsoft').
        """
        logger.info("Tool called: alpha_vantage_search_symbol keywords=%s", keywords)
        result = ApiServiceAlphaVantageCoreStock(CONFIG).search_symbol(keywords)
        return _as_dict(result)

    @mcp.tool()
    def alpha_vantage_market_status() -> dict:
        """Get the current open/closed status for global trading venues."""
        logger.info("Tool called: alpha_vantage_market_status")
        result = ApiServiceAlphaVantageCoreStock(CONFIG).get_market_status()
        return _as_dict(result)

    @mcp.tool()
    def alpha_vantage_time_series_intraday(symbol: str, interval: str = '5min',
                                           outputsize: str = 'compact') -> dict:
        """Get intraday OHLCV time series for a ticker.

        Args:
            symbol: Equity ticker.
            interval: '1min', '5min', '15min', '30min', '60min'. Default '5min'.
            outputsize: 'compact' (latest 100) or 'full' (full history). Default 'compact'.
        """
        logger.info("Tool called: alpha_vantage_time_series_intraday symbol=%s interval=%s",
                    symbol, interval)
        result = ApiServiceAlphaVantageCoreStock(CONFIG).get_intraday(
            symbol, interval=interval, outputsize=outputsize)
        return _as_dict(result)

    @mcp.tool()
    def alpha_vantage_time_series_daily(symbol: str, outputsize: str = 'compact',
                                        adjusted: bool = False) -> dict:
        """Get daily OHLCV time series.

        Args:
            symbol: Equity ticker.
            outputsize: 'compact' (latest 100) or 'full'. Default 'compact'.
            adjusted: True for split/dividend-adjusted closes. Default False.
        """
        logger.info("Tool called: alpha_vantage_time_series_daily symbol=%s adjusted=%s",
                    symbol, adjusted)
        svc = ApiServiceAlphaVantageCoreStock(CONFIG)
        if adjusted:
            result = svc.get_daily_adjusted(symbol, outputsize=outputsize)
        else:
            result = svc.get_daily(symbol, outputsize=outputsize)
        return _as_dict(result)

    # ── FX ─────────────────────────────────────────────────────────────────

    @mcp.tool()
    def alpha_vantage_fx_rate(from_currency: str, to_currency: str) -> dict:
        """Get the realtime exchange rate between two currencies (also supports crypto codes).

        Args:
            from_currency: ISO code or crypto ticker (e.g. 'USD', 'EUR', 'BTC').
            to_currency: ISO code or crypto ticker (e.g. 'JPY', 'USD').
        """
        logger.info("Tool called: alpha_vantage_fx_rate %s->%s", from_currency, to_currency)
        result = ApiServiceAlphaVantageFx(CONFIG).get_exchange_rate(from_currency, to_currency)
        return _as_dict(result)

    @mcp.tool()
    def alpha_vantage_convert_currency(amount: float, from_currency: str, to_currency: str) -> dict:
        """Convert an amount between two currencies using the realtime rate.

        Args:
            amount: Amount to convert.
            from_currency: ISO code (e.g. 'USD').
            to_currency: ISO code (e.g. 'EUR').
        """
        logger.info("Tool called: alpha_vantage_convert_currency %s %s->%s",
                    amount, from_currency, to_currency)
        result = ApiServiceAlphaVantageFx(CONFIG).convert_currency(amount, from_currency, to_currency)
        return _as_dict(result)

    @mcp.tool()
    def alpha_vantage_fx_intraday(from_symbol: str, to_symbol: str,
                                  interval: str = '5min', outputsize: str = 'compact') -> dict:
        """Intraday FX time series for a currency pair.

        Args:
            from_symbol: Three-letter ISO code (e.g. 'EUR').
            to_symbol: Three-letter ISO code (e.g. 'USD').
            interval: '1min', '5min', '15min', '30min', '60min'. Default '5min'.
            outputsize: 'compact' or 'full'. Default 'compact'.
        """
        logger.info("Tool called: alpha_vantage_fx_intraday %s%s interval=%s",
                    from_symbol, to_symbol, interval)
        result = ApiServiceAlphaVantageFx(CONFIG).get_fx_intraday(
            from_symbol, to_symbol, interval=interval, outputsize=outputsize)
        return _as_dict(result)

    @mcp.tool()
    def alpha_vantage_fx_daily(from_symbol: str, to_symbol: str,
                               outputsize: str = 'compact') -> dict:
        """Daily OHLC FX time series for a currency pair."""
        logger.info("Tool called: alpha_vantage_fx_daily %s%s", from_symbol, to_symbol)
        result = ApiServiceAlphaVantageFx(CONFIG).get_fx_daily(
            from_symbol, to_symbol, outputsize=outputsize)
        return _as_dict(result)

    # ── News & Sentiment ──────────────────────────────────────────────────

    @mcp.tool()
    def alpha_vantage_news_sentiment(tickers: str = None, topics: str = None,
                                     time_from: str = None, time_to: str = None,
                                     sort: str = 'LATEST', limit: int = 50) -> dict:
        """Market news with per-article sentiment scoring. Use this for finance/FX news.

        Args:
            tickers: Comma-separated tickers (e.g. 'AAPL,MSFT' or 'FOREX:USD' / 'CRYPTO:BTC').
            topics: Comma-separated topic names — blockchain, earnings, ipo,
                mergers_and_acquisitions, financial_markets, economy_fiscal,
                economy_monetary, economy_macro, energy_transportation, finance,
                life_sciences, manufacturing, real_estate, retail_wholesale, technology.
            time_from: Start datetime 'YYYYMMDDTHHMM'.
            time_to: End datetime 'YYYYMMDDTHHMM'.
            sort: 'LATEST' (default), 'EARLIEST', or 'RELEVANCE'.
            limit: Max articles (default 50, max 1000).
        """
        logger.info("Tool called: alpha_vantage_news_sentiment tickers=%s topics=%s limit=%s",
                    tickers, topics, limit)
        result = ApiServiceAlphaVantageNews(CONFIG).get_news_sentiment(
            tickers=tickers, topics=topics, time_from=time_from, time_to=time_to,
            sort=sort, limit=limit)
        return _as_dict(result)

    @mcp.tool()
    def alpha_vantage_top_gainers_losers() -> dict:
        """Get the daily top gainers, losers, and most actively traded US stocks."""
        logger.info("Tool called: alpha_vantage_top_gainers_losers")
        result = ApiServiceAlphaVantageNews(CONFIG).get_top_gainers_losers()
        return _as_dict(result)

    @mcp.tool()
    def alpha_vantage_insider_transactions(symbol: str) -> dict:
        """Get the latest insider transactions for a company.

        Args:
            symbol: Equity ticker.
        """
        logger.info("Tool called: alpha_vantage_insider_transactions symbol=%s", symbol)
        result = ApiServiceAlphaVantageNews(CONFIG).get_insider_transactions(symbol)
        return _as_dict(result)

    @mcp.tool()
    def alpha_vantage_earnings_call_transcript(symbol: str, quarter: str = None) -> dict:
        """Get an earnings call transcript for a company.

        Args:
            symbol: Equity ticker.
            quarter: Optional 'YYYYQM' (e.g. '2024Q1') for a specific quarter.
        """
        logger.info("Tool called: alpha_vantage_earnings_call_transcript symbol=%s quarter=%s",
                    symbol, quarter)
        result = ApiServiceAlphaVantageNews(CONFIG).get_earnings_call_transcript(symbol, quarter)
        return _as_dict(result)

    # ── Fundamentals ──────────────────────────────────────────────────────

    @mcp.tool()
    def alpha_vantage_company_overview(symbol: str) -> dict:
        """Get company description, sector, financial ratios, and key metrics.

        Args:
            symbol: Equity ticker.
        """
        logger.info("Tool called: alpha_vantage_company_overview symbol=%s", symbol)
        result = ApiServiceAlphaVantageFundamentals(CONFIG).get_overview(symbol)
        return _as_dict(result)

    @mcp.tool()
    def alpha_vantage_etf_profile(symbol: str) -> dict:
        """Get ETF holdings, sector allocation, and expense ratio.

        Args:
            symbol: ETF ticker.
        """
        logger.info("Tool called: alpha_vantage_etf_profile symbol=%s", symbol)
        result = ApiServiceAlphaVantageFundamentals(CONFIG).get_etf_profile(symbol)
        return _as_dict(result)

    @mcp.tool()
    def alpha_vantage_income_statement(symbol: str) -> dict:
        """Get annual and quarterly income statements for a company.

        Args:
            symbol: Equity ticker.
        """
        logger.info("Tool called: alpha_vantage_income_statement symbol=%s", symbol)
        result = ApiServiceAlphaVantageFundamentals(CONFIG).get_income_statement(symbol)
        return _as_dict(result)

    @mcp.tool()
    def alpha_vantage_balance_sheet(symbol: str) -> dict:
        """Get annual and quarterly balance sheets for a company.

        Args:
            symbol: Equity ticker.
        """
        logger.info("Tool called: alpha_vantage_balance_sheet symbol=%s", symbol)
        result = ApiServiceAlphaVantageFundamentals(CONFIG).get_balance_sheet(symbol)
        return _as_dict(result)

    @mcp.tool()
    def alpha_vantage_cash_flow(symbol: str) -> dict:
        """Get annual and quarterly cash flow statements for a company.

        Args:
            symbol: Equity ticker.
        """
        logger.info("Tool called: alpha_vantage_cash_flow symbol=%s", symbol)
        result = ApiServiceAlphaVantageFundamentals(CONFIG).get_cash_flow(symbol)
        return _as_dict(result)

    @mcp.tool()
    def alpha_vantage_earnings(symbol: str) -> dict:
        """Get historical earnings dates and reported EPS for a company.

        Args:
            symbol: Equity ticker.
        """
        logger.info("Tool called: alpha_vantage_earnings symbol=%s", symbol)
        result = ApiServiceAlphaVantageFundamentals(CONFIG).get_earnings(symbol)
        return _as_dict(result)

    @mcp.tool()
    def alpha_vantage_dividends(symbol: str) -> dict:
        """Get historical and upcoming dividend events for a company.

        Args:
            symbol: Equity ticker.
        """
        logger.info("Tool called: alpha_vantage_dividends symbol=%s", symbol)
        result = ApiServiceAlphaVantageFundamentals(CONFIG).get_dividends(symbol)
        return _as_dict(result)

    # ── Technical Indicators ──────────────────────────────────────────────

    @mcp.tool()
    def alpha_vantage_indicator(function: str, symbol: str, interval: str = 'daily',
                                time_period: int = None, series_type: str = None) -> dict:
        """Generic technical indicator dispatcher — supports the full Alpha Vantage list.

        Use this for any indicator (SMA, EMA, RSI, MACD, BBANDS, ADX, ATR, STOCH, OBV,
        and 40+ more — see https://www.alphavantage.co/documentation/#technical-indicators).
        For indicators with extra params (e.g. MACD's fastperiod/slowperiod/signalperiod,
        BBANDS's nbdevup/nbdevdn) call the underlying ApiServiceAlphaVantageTechnicals
        directly via Python — this MCP tool covers the most common (time_period, series_type) shape.

        Args:
            function: Indicator function name (e.g. 'SMA', 'RSI', 'MACD', 'BBANDS').
            symbol: Equity ticker.
            interval: '1min', '5min', '15min', '30min', '60min', 'daily', 'weekly', 'monthly'.
            time_period: Look-back window for indicators that take one (e.g. 14 for RSI).
            series_type: 'close', 'open', 'high', 'low' for indicators that pick a series.
        """
        logger.info("Tool called: alpha_vantage_indicator function=%s symbol=%s interval=%s",
                    function, symbol, interval)
        kwargs = {}
        if time_period is not None:
            kwargs['time_period'] = time_period
        if series_type is not None:
            kwargs['series_type'] = series_type
        result = ApiServiceAlphaVantageTechnicals(CONFIG).get_indicator(
            function, symbol, interval=interval, **kwargs)
        return _as_dict(result)

    @mcp.tool()
    def alpha_vantage_rsi(symbol: str, interval: str = 'daily',
                          time_period: int = 14, series_type: str = 'close') -> dict:
        """Relative Strength Index — momentum oscillator (0-100).

        Args:
            symbol: Equity ticker.
            interval: '1min', '5min', '15min', '30min', '60min', 'daily', 'weekly', 'monthly'.
            time_period: Look-back window (default 14).
            series_type: 'close', 'open', 'high', 'low'. Default 'close'.
        """
        logger.info("Tool called: alpha_vantage_rsi symbol=%s interval=%s period=%s",
                    symbol, interval, time_period)
        result = ApiServiceAlphaVantageTechnicals(CONFIG).rsi(
            symbol, interval=interval, time_period=time_period, series_type=series_type)
        return _as_dict(result)

    @mcp.tool()
    def alpha_vantage_macd(symbol: str, interval: str = 'daily',
                           series_type: str = 'close',
                           fastperiod: int = 12, slowperiod: int = 26,
                           signalperiod: int = 9) -> dict:
        """MACD — Moving Average Convergence/Divergence with signal line.

        Args:
            symbol: Equity ticker.
            interval: '1min'..'60min', 'daily', 'weekly', 'monthly'.
            series_type: 'close' (default), 'open', 'high', 'low'.
            fastperiod: Fast EMA period (default 12).
            slowperiod: Slow EMA period (default 26).
            signalperiod: Signal line period (default 9).
        """
        logger.info("Tool called: alpha_vantage_macd symbol=%s interval=%s",
                    symbol, interval)
        result = ApiServiceAlphaVantageTechnicals(CONFIG).macd(
            symbol, interval=interval, series_type=series_type,
            fastperiod=fastperiod, slowperiod=slowperiod, signalperiod=signalperiod)
        return _as_dict(result)

    @mcp.tool()
    def alpha_vantage_sma(symbol: str, interval: str = 'daily',
                          time_period: int = 20, series_type: str = 'close') -> dict:
        """Simple Moving Average."""
        logger.info("Tool called: alpha_vantage_sma symbol=%s period=%s", symbol, time_period)
        result = ApiServiceAlphaVantageTechnicals(CONFIG).sma(
            symbol, interval=interval, time_period=time_period, series_type=series_type)
        return _as_dict(result)

    @mcp.tool()
    def alpha_vantage_ema(symbol: str, interval: str = 'daily',
                          time_period: int = 20, series_type: str = 'close') -> dict:
        """Exponential Moving Average."""
        logger.info("Tool called: alpha_vantage_ema symbol=%s period=%s", symbol, time_period)
        result = ApiServiceAlphaVantageTechnicals(CONFIG).ema(
            symbol, interval=interval, time_period=time_period, series_type=series_type)
        return _as_dict(result)

    @mcp.tool()
    def alpha_vantage_bbands(symbol: str, interval: str = 'daily',
                             time_period: int = 20, series_type: str = 'close',
                             nbdevup: int = 2, nbdevdn: int = 2) -> dict:
        """Bollinger Bands — volatility envelope."""
        logger.info("Tool called: alpha_vantage_bbands symbol=%s period=%s", symbol, time_period)
        result = ApiServiceAlphaVantageTechnicals(CONFIG).bbands(
            symbol, interval=interval, time_period=time_period, series_type=series_type,
            nbdevup=nbdevup, nbdevdn=nbdevdn)
        return _as_dict(result)

    # ── Crypto ────────────────────────────────────────────────────────────

    @mcp.tool()
    def alpha_vantage_crypto_intraday(symbol: str, market: str = 'USD',
                                      interval: str = '5min') -> dict:
        """Intraday OHLCV for a cryptocurrency.

        Args:
            symbol: Crypto symbol (e.g. 'ETH', 'BTC').
            market: Quote market (default 'USD').
            interval: '1min', '5min', '15min', '30min', '60min'.
        """
        logger.info("Tool called: alpha_vantage_crypto_intraday %s/%s", symbol, market)
        result = ApiServiceAlphaVantageCrypto(CONFIG).get_crypto_intraday(
            symbol, market=market, interval=interval)
        return _as_dict(result)

    @mcp.tool()
    def alpha_vantage_crypto_daily(symbol: str, market: str = 'USD') -> dict:
        """Daily exchange rates for a cryptocurrency.

        Args:
            symbol: Crypto symbol (e.g. 'BTC').
            market: Quote market (default 'USD').
        """
        logger.info("Tool called: alpha_vantage_crypto_daily %s/%s", symbol, market)
        result = ApiServiceAlphaVantageCrypto(CONFIG).get_digital_currency_daily(symbol, market)
        return _as_dict(result)

    # ── Commodities ───────────────────────────────────────────────────────

    @mcp.tool()
    def alpha_vantage_commodity(name: str, interval: str = 'monthly') -> dict:
        """Get commodity price time series.

        Args:
            name: One of 'WTI', 'BRENT', 'NATURAL_GAS', 'COPPER', 'ALUMINUM',
                  'WHEAT', 'CORN', 'COTTON', 'SUGAR', 'COFFEE', 'ALL_COMMODITIES'.
            interval: 'daily', 'weekly', 'monthly' (default 'monthly').
        """
        logger.info("Tool called: alpha_vantage_commodity name=%s interval=%s", name, interval)
        svc = ApiServiceAlphaVantageCommodities(CONFIG)
        method_name = 'get_' + name.lower()
        method = getattr(svc, method_name, None)
        if method is None:
            return {"error": f"Unknown commodity '{name}'. Use one of: WTI, BRENT, NATURAL_GAS, "
                             f"COPPER, ALUMINUM, WHEAT, CORN, COTTON, SUGAR, COFFEE, ALL_COMMODITIES."}
        return _as_dict(method(interval=interval))

    # ── Economic Indicators ───────────────────────────────────────────────

    @mcp.tool()
    def alpha_vantage_economic_indicator(name: str, interval: str = None,
                                         maturity: str = None) -> dict:
        """Get a US economic indicator time series.

        Args:
            name: One of 'REAL_GDP', 'REAL_GDP_PER_CAPITA', 'TREASURY_YIELD',
                  'FEDERAL_FUNDS_RATE', 'CPI', 'INFLATION', 'RETAIL_SALES',
                  'DURABLES', 'UNEMPLOYMENT', 'NONFARM_PAYROLL'.
            interval: For indicators that support it: 'daily', 'weekly', 'monthly',
                      'quarterly', 'annual', or 'semiannual' (CPI).
            maturity: For TREASURY_YIELD only: '3month', '2year', '5year',
                      '7year', '10year', '30year'.
        """
        logger.info("Tool called: alpha_vantage_economic_indicator name=%s interval=%s",
                    name, interval)
        svc = ApiServiceAlphaVantageEconomic(CONFIG)
        n = name.upper()
        if n == 'REAL_GDP':
            return _as_dict(svc.get_real_gdp(interval=interval or 'annual'))
        if n == 'REAL_GDP_PER_CAPITA':
            return _as_dict(svc.get_real_gdp_per_capita())
        if n == 'TREASURY_YIELD':
            return _as_dict(svc.get_treasury_yield(
                interval=interval or 'monthly', maturity=maturity or '10year'))
        if n == 'FEDERAL_FUNDS_RATE':
            return _as_dict(svc.get_federal_funds_rate(interval=interval or 'monthly'))
        if n == 'CPI':
            return _as_dict(svc.get_cpi(interval=interval or 'monthly'))
        if n == 'INFLATION':
            return _as_dict(svc.get_inflation())
        if n == 'RETAIL_SALES':
            return _as_dict(svc.get_retail_sales())
        if n == 'DURABLES':
            return _as_dict(svc.get_durables())
        if n == 'UNEMPLOYMENT':
            return _as_dict(svc.get_unemployment())
        if n == 'NONFARM_PAYROLL':
            return _as_dict(svc.get_nonfarm_payroll())
        return {"error": f"Unknown indicator '{name}'."}
