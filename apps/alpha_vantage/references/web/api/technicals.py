"""
Technical Indicator APIs (50+ indicators).

Reference: https://www.alphavantage.co/documentation/#technical-indicators

The full list is too long to wrap one method per indicator, so this service
exposes a generic `get_indicator(function, ...)` with the most common indicators
also provided as named convenience methods. To support a new indicator, no code
change is needed — pass the function name (e.g. 'TRIX') and the docs' params.
"""
from apps.alpha_vantage.references.web.base_api_service import BaseApiServiceAlphaVantage
from core.web.services.core.decorators.deserializer import deserialized


# Reference set — every indicator the docs lists today. Used for validation
# / discovery; not enforced (so newly-added indicators still work).
SUPPORTED_INDICATORS = [
    # Moving averages
    'SMA', 'EMA', 'WMA', 'DEMA', 'TEMA', 'TRIMA', 'KAMA', 'MAMA', 'T3',
    # MACD family
    'MACD', 'MACDEXT',
    # Stochastic & RSI family
    'STOCH', 'STOCHF', 'RSI', 'STOCHRSI', 'WILLR',
    # Directional / oscillators
    'ADX', 'ADXR', 'APO', 'PPO', 'MOM', 'BOP', 'CCI', 'CMO', 'ROC', 'ROCR',
    'AROON', 'AROONOSC', 'MFI', 'TRIX', 'ULTOSC', 'DX',
    'MINUS_DI', 'PLUS_DI', 'MINUS_DM', 'PLUS_DM',
    # Volatility / bands
    'BBANDS', 'MIDPOINT', 'MIDPRICE', 'SAR', 'TRANGE', 'ATR', 'NATR',
    # Volume
    'AD', 'ADOSC', 'OBV',
    # Hilbert Transform
    'HT_TRENDLINE', 'HT_SINE', 'HT_TRENDMODE', 'HT_DCPERIOD', 'HT_DCPHASE', 'HT_PHASOR',
]


class ApiServiceAlphaVantageTechnicals(BaseApiServiceAlphaVantage):
    """Technical indicators — generic dispatcher + common helpers."""

    def __init__(self, config, **kwargs):
        super(ApiServiceAlphaVantageTechnicals, self).__init__(config, **kwargs)

    @deserialized(dict)
    def get_indicator(self, function, symbol, interval='daily', **kwargs):
        """Generic indicator dispatcher.

        Args:
            function: Indicator name (e.g. 'SMA', 'RSI', 'MACD'). Any function
                listed in SUPPORTED_INDICATORS or any new indicator the docs
                add later. The function is passed straight to Alpha Vantage.
            symbol: Equity ticker.
            interval: '1min', '5min', '15min', '30min', '60min', 'daily',
                'weekly', or 'monthly'. Default 'daily'.
            **kwargs: Indicator-specific params from the docs, e.g.
                time_period, series_type, fastperiod, slowperiod, signalperiod,
                nbdevup, nbdevdn, fastkperiod, slowkperiod, slowdperiod, etc.
        """
        return self._query(function, symbol=symbol, interval=interval, **kwargs)

    # ── Common convenience wrappers ──────────────────────────────────────

    def sma(self, symbol, interval='daily', time_period=20, series_type='close'):
        """function=SMA — Simple Moving Average."""
        return self.get_indicator('SMA', symbol, interval=interval,
                                  time_period=time_period, series_type=series_type)

    def ema(self, symbol, interval='daily', time_period=20, series_type='close'):
        """function=EMA — Exponential Moving Average."""
        return self.get_indicator('EMA', symbol, interval=interval,
                                  time_period=time_period, series_type=series_type)

    def rsi(self, symbol, interval='daily', time_period=14, series_type='close'):
        """function=RSI — Relative Strength Index."""
        return self.get_indicator('RSI', symbol, interval=interval,
                                  time_period=time_period, series_type=series_type)

    def macd(self, symbol, interval='daily', series_type='close',
             fastperiod=12, slowperiod=26, signalperiod=9):
        """function=MACD — Moving Average Convergence/Divergence."""
        return self.get_indicator('MACD', symbol, interval=interval,
                                  series_type=series_type,
                                  fastperiod=fastperiod, slowperiod=slowperiod,
                                  signalperiod=signalperiod)

    def bbands(self, symbol, interval='daily', time_period=20, series_type='close',
               nbdevup=2, nbdevdn=2):
        """function=BBANDS — Bollinger Bands."""
        return self.get_indicator('BBANDS', symbol, interval=interval,
                                  time_period=time_period, series_type=series_type,
                                  nbdevup=nbdevup, nbdevdn=nbdevdn)

    def adx(self, symbol, interval='daily', time_period=14):
        """function=ADX — Average Directional Index."""
        return self.get_indicator('ADX', symbol, interval=interval, time_period=time_period)

    def atr(self, symbol, interval='daily', time_period=14):
        """function=ATR — Average True Range."""
        return self.get_indicator('ATR', symbol, interval=interval, time_period=time_period)

    def stoch(self, symbol, interval='daily',
              fastkperiod=5, slowkperiod=3, slowdperiod=3,
              slowkmatype=0, slowdmatype=0):
        """function=STOCH — Stochastic Oscillator."""
        return self.get_indicator('STOCH', symbol, interval=interval,
                                  fastkperiod=fastkperiod, slowkperiod=slowkperiod,
                                  slowdperiod=slowdperiod,
                                  slowkmatype=slowkmatype, slowdmatype=slowdmatype)

    def obv(self, symbol, interval='daily'):
        """function=OBV — On-Balance Volume."""
        return self.get_indicator('OBV', symbol, interval=interval)
