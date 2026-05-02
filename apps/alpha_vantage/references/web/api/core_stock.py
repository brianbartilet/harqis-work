"""
Core Stock APIs.

Reference: https://www.alphavantage.co/documentation/#time-series-data
"""
from apps.alpha_vantage.references.web.base_api_service import BaseApiServiceAlphaVantage
from core.web.services.core.decorators.deserializer import deserialized


class ApiServiceAlphaVantageCoreStock(BaseApiServiceAlphaVantage):
    """Core Stock — quotes, time series, search, market status."""

    def __init__(self, config, **kwargs):
        super(ApiServiceAlphaVantageCoreStock, self).__init__(config, **kwargs)

    @deserialized(dict)
    def get_intraday(self, symbol, interval='5min', adjusted=None, extended_hours=None,
                     month=None, outputsize=None, datatype=None):
        """function=TIME_SERIES_INTRADAY — current and 20+ years of intraday OHLCV.

        Args:
            symbol: Equity ticker (e.g. 'IBM').
            interval: '1min', '5min', '15min', '30min', '60min'. Default '5min'.
            adjusted: 'true'/'false'.
            extended_hours: 'true'/'false'.
            month: 'YYYY-MM' to fetch a specific historical month.
            outputsize: 'compact' (latest 100) or 'full'.
            datatype: 'json' or 'csv'.
        """
        return self._query('TIME_SERIES_INTRADAY', symbol=symbol, interval=interval,
                           adjusted=adjusted, extended_hours=extended_hours, month=month,
                           outputsize=outputsize, datatype=datatype)

    @deserialized(dict)
    def get_daily(self, symbol, outputsize=None, datatype=None):
        """function=TIME_SERIES_DAILY — raw daily OHLCV across 20+ years."""
        return self._query('TIME_SERIES_DAILY', symbol=symbol,
                           outputsize=outputsize, datatype=datatype)

    @deserialized(dict)
    def get_daily_adjusted(self, symbol, outputsize=None, datatype=None):
        """function=TIME_SERIES_DAILY_ADJUSTED — daily with adjusted close, splits and dividends."""
        return self._query('TIME_SERIES_DAILY_ADJUSTED', symbol=symbol,
                           outputsize=outputsize, datatype=datatype)

    @deserialized(dict)
    def get_weekly(self, symbol, datatype=None):
        """function=TIME_SERIES_WEEKLY — weekly OHLCV."""
        return self._query('TIME_SERIES_WEEKLY', symbol=symbol, datatype=datatype)

    @deserialized(dict)
    def get_weekly_adjusted(self, symbol, datatype=None):
        """function=TIME_SERIES_WEEKLY_ADJUSTED — weekly adjusted with dividends."""
        return self._query('TIME_SERIES_WEEKLY_ADJUSTED', symbol=symbol, datatype=datatype)

    @deserialized(dict)
    def get_monthly(self, symbol, datatype=None):
        """function=TIME_SERIES_MONTHLY — monthly OHLCV."""
        return self._query('TIME_SERIES_MONTHLY', symbol=symbol, datatype=datatype)

    @deserialized(dict)
    def get_monthly_adjusted(self, symbol, datatype=None):
        """function=TIME_SERIES_MONTHLY_ADJUSTED — monthly adjusted with dividends."""
        return self._query('TIME_SERIES_MONTHLY_ADJUSTED', symbol=symbol, datatype=datatype)

    @deserialized(dict)
    def get_global_quote(self, symbol, datatype=None):
        """function=GLOBAL_QUOTE — latest price and volume for a single ticker."""
        return self._query('GLOBAL_QUOTE', symbol=symbol, datatype=datatype)

    @deserialized(dict)
    def get_realtime_bulk_quotes(self, symbols, datatype=None):
        """function=REALTIME_BULK_QUOTES — up to 100 US-traded symbols.

        Args:
            symbols: Comma-separated ticker list (e.g. 'IBM,AAPL,MSFT').
        """
        return self._query('REALTIME_BULK_QUOTES', symbol=symbols, datatype=datatype)

    @deserialized(dict)
    def search_symbol(self, keywords, datatype=None):
        """function=SYMBOL_SEARCH — search by company name or keyword."""
        return self._query('SYMBOL_SEARCH', keywords=keywords, datatype=datatype)

    @deserialized(dict)
    def get_market_status(self):
        """function=MARKET_STATUS — open/closed status for global trading venues."""
        return self._query('MARKET_STATUS')
