"""
Cryptocurrency APIs.

Reference: https://www.alphavantage.co/documentation/#digital-currency
"""
from apps.alpha_vantage.references.web.base_api_service import BaseApiServiceAlphaVantage
from core.web.services.core.decorators.deserializer import deserialized


class ApiServiceAlphaVantageCrypto(BaseApiServiceAlphaVantage):
    """Crypto — exchange rates and digital currency time series."""

    def __init__(self, config, **kwargs):
        super(ApiServiceAlphaVantageCrypto, self).__init__(config, **kwargs)

    @deserialized(dict)
    def get_crypto_intraday(self, symbol, market='USD', interval='5min',
                            outputsize=None, datatype=None):
        """function=CRYPTO_INTRADAY — intraday crypto OHLCV.

        Args:
            symbol: Crypto symbol (e.g. 'ETH').
            market: Quote market (e.g. 'USD').
            interval: '1min', '5min', '15min', '30min', '60min'.
        """
        return self._query('CRYPTO_INTRADAY',
                           symbol=symbol, market=market, interval=interval,
                           outputsize=outputsize, datatype=datatype)

    @deserialized(dict)
    def get_digital_currency_daily(self, symbol, market='USD', datatype=None):
        """function=DIGITAL_CURRENCY_DAILY — daily crypto exchange rates."""
        return self._query('DIGITAL_CURRENCY_DAILY',
                           symbol=symbol, market=market, datatype=datatype)

    @deserialized(dict)
    def get_digital_currency_weekly(self, symbol, market='USD', datatype=None):
        """function=DIGITAL_CURRENCY_WEEKLY — weekly crypto exchange rates."""
        return self._query('DIGITAL_CURRENCY_WEEKLY',
                           symbol=symbol, market=market, datatype=datatype)

    @deserialized(dict)
    def get_digital_currency_monthly(self, symbol, market='USD', datatype=None):
        """function=DIGITAL_CURRENCY_MONTHLY — monthly crypto exchange rates."""
        return self._query('DIGITAL_CURRENCY_MONTHLY',
                           symbol=symbol, market=market, datatype=datatype)
