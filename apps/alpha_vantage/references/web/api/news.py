"""
Alpha Intelligence — news, sentiment, and trading signals.

Reference: https://www.alphavantage.co/documentation/#intelligence
"""
from apps.alpha_vantage.references.web.base_api_service import BaseApiServiceAlphaVantage
from core.web.services.core.decorators.deserializer import deserialized


class ApiServiceAlphaVantageNews(BaseApiServiceAlphaVantage):
    """News, sentiment, top movers, insider transactions, analytics."""

    def __init__(self, config, **kwargs):
        super(ApiServiceAlphaVantageNews, self).__init__(config, **kwargs)

    @deserialized(dict)
    def get_news_sentiment(self, tickers=None, topics=None, time_from=None, time_to=None,
                           sort=None, limit=None, datatype=None):
        """function=NEWS_SENTIMENT — market news with per-article sentiment scoring.

        Args:
            tickers: Comma-separated ticker list (e.g. 'AAPL,MSFT'). For FX use
                'FOREX:USD' / 'CRYPTO:BTC' style prefixes.
            topics: Comma-separated topic list. Supported topics include:
                blockchain, earnings, ipo, mergers_and_acquisitions, financial_markets,
                economy_fiscal, economy_monetary, economy_macro, energy_transportation,
                finance, life_sciences, manufacturing, real_estate, retail_wholesale,
                technology.
            time_from: Start datetime 'YYYYMMDDTHHMM'.
            time_to: End datetime 'YYYYMMDDTHHMM'.
            sort: 'LATEST' (default), 'EARLIEST', or 'RELEVANCE'.
            limit: Max articles (default 50, max 1000).
            datatype: 'json' or 'csv'.
        """
        return self._query('NEWS_SENTIMENT',
                           tickers=tickers, topics=topics,
                           time_from=time_from, time_to=time_to,
                           sort=sort, limit=limit, datatype=datatype)

    @deserialized(dict)
    def get_earnings_call_transcript(self, symbol, quarter=None):
        """function=EARNINGS_CALL_TRANSCRIPT — earnings call transcript for a company.

        Args:
            symbol: Equity ticker.
            quarter: 'YYYYQM' (e.g. '2024Q1') for a specific quarter.
        """
        return self._query('EARNINGS_CALL_TRANSCRIPT', symbol=symbol, quarter=quarter)

    @deserialized(dict)
    def get_top_gainers_losers(self, datatype=None):
        """function=TOP_GAINERS_LOSERS — daily top gainers, losers, and most active US stocks."""
        return self._query('TOP_GAINERS_LOSERS', datatype=datatype)

    @deserialized(dict)
    def get_insider_transactions(self, symbol):
        """function=INSIDER_TRANSACTIONS — latest insider buys/sells for a company."""
        return self._query('INSIDER_TRANSACTIONS', symbol=symbol)

    @deserialized(dict)
    def get_analytics_fixed_window(self, symbols, range_, interval, calculations,
                                   ohlc=None, datatype=None):
        """function=ANALYTICS_FIXED_WINDOW — analytics over a fixed time window.

        Args:
            symbols: Comma-separated ticker list.
            range_: e.g. '2023-07-01' or '6month'. Mapped to the API's `range`.
            interval: 'DAILY', 'WEEKLY', 'MONTHLY'.
            calculations: Comma-separated list, e.g.
                'MEAN,STDDEV,CORRELATION,COVARIANCE,MIN,MAX,AUTOCORRELATION,CUMULATIVE_RETURN'.
            ohlc: 'open' / 'high' / 'low' / 'close'.
        """
        params = {
            'SYMBOLS': symbols,
            'RANGE': range_,
            'INTERVAL': interval,
            'CALCULATIONS': calculations,
            'OHLC': ohlc,
            'datatype': datatype,
        }
        return self._query('ANALYTICS_FIXED_WINDOW', **params)

    @deserialized(dict)
    def get_analytics_sliding_window(self, symbols, range_, interval, window_size,
                                     calculations, ohlc=None, datatype=None):
        """function=ANALYTICS_SLIDING_WINDOW — rolling-window analytics.

        Args:
            window_size: Integer rolling window length in number of intervals.
        """
        params = {
            'SYMBOLS': symbols,
            'RANGE': range_,
            'INTERVAL': interval,
            'WINDOW_SIZE': window_size,
            'CALCULATIONS': calculations,
            'OHLC': ohlc,
            'datatype': datatype,
        }
        return self._query('ANALYTICS_SLIDING_WINDOW', **params)
