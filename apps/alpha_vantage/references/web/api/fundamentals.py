"""
Fundamental Data APIs.

Reference: https://www.alphavantage.co/documentation/#fundamentals
"""
from apps.alpha_vantage.references.web.base_api_service import BaseApiServiceAlphaVantage
from core.web.services.core.decorators.deserializer import deserialized


class ApiServiceAlphaVantageFundamentals(BaseApiServiceAlphaVantage):
    """Fundamentals — overview, financial statements, earnings, calendars."""

    def __init__(self, config, **kwargs):
        super(ApiServiceAlphaVantageFundamentals, self).__init__(config, **kwargs)

    @deserialized(dict)
    def get_overview(self, symbol):
        """function=OVERVIEW — company description, ratios, market cap, etc."""
        return self._query('OVERVIEW', symbol=symbol)

    @deserialized(dict)
    def get_etf_profile(self, symbol):
        """function=ETF_PROFILE — ETF holdings, sector allocation, expense ratio."""
        return self._query('ETF_PROFILE', symbol=symbol)

    @deserialized(dict)
    def get_dividends(self, symbol):
        """function=DIVIDENDS — historical and upcoming dividend events."""
        return self._query('DIVIDENDS', symbol=symbol)

    @deserialized(dict)
    def get_splits(self, symbol):
        """function=SPLITS — historical stock split events."""
        return self._query('SPLITS', symbol=symbol)

    @deserialized(dict)
    def get_income_statement(self, symbol):
        """function=INCOME_STATEMENT — annual + quarterly income statements."""
        return self._query('INCOME_STATEMENT', symbol=symbol)

    @deserialized(dict)
    def get_balance_sheet(self, symbol):
        """function=BALANCE_SHEET — annual + quarterly balance sheets."""
        return self._query('BALANCE_SHEET', symbol=symbol)

    @deserialized(dict)
    def get_cash_flow(self, symbol):
        """function=CASH_FLOW — annual + quarterly cash flow statements."""
        return self._query('CASH_FLOW', symbol=symbol)

    @deserialized(dict)
    def get_earnings(self, symbol):
        """function=EARNINGS — historical earnings dates and EPS."""
        return self._query('EARNINGS', symbol=symbol)

    def get_listing_status(self, date=None, state=None):
        """function=LISTING_STATUS — listed/delisted securities (CSV response).

        Args:
            date: 'YYYY-MM-DD' to query a historical snapshot.
            state: 'active' (default) or 'delisted'.
        """
        return self._query('LISTING_STATUS', date=date, state=state)

    def get_earnings_calendar(self, symbol=None, horizon=None):
        """function=EARNINGS_CALENDAR — upcoming earnings (CSV response).

        Args:
            symbol: Optional single ticker filter.
            horizon: '3month' (default), '6month', '12month'.
        """
        return self._query('EARNINGS_CALENDAR', symbol=symbol, horizon=horizon)

    def get_ipo_calendar(self):
        """function=IPO_CALENDAR — upcoming IPOs (CSV response)."""
        return self._query('IPO_CALENDAR')
