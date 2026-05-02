"""
Forex (FX) APIs.

Reference: https://www.alphavantage.co/documentation/#fx
"""
from apps.alpha_vantage.references.web.base_api_service import BaseApiServiceAlphaVantage
from core.web.services.core.decorators.deserializer import deserialized


class ApiServiceAlphaVantageFx(BaseApiServiceAlphaVantage):
    """Forex — exchange rates and FX time series."""

    def __init__(self, config, **kwargs):
        super(ApiServiceAlphaVantageFx, self).__init__(config, **kwargs)

    @deserialized(dict)
    def get_exchange_rate(self, from_currency, to_currency, datatype=None):
        """function=CURRENCY_EXCHANGE_RATE — realtime FX rate.

        Also supports crypto codes (e.g. from_currency='BTC', to_currency='USD').
        """
        return self._query('CURRENCY_EXCHANGE_RATE',
                           from_currency=from_currency, to_currency=to_currency,
                           datatype=datatype)

    @deserialized(dict)
    def get_fx_intraday(self, from_symbol, to_symbol, interval='5min',
                        outputsize=None, datatype=None, month=None):
        """function=FX_INTRADAY — intraday FX time series.

        Args:
            from_symbol: Three-letter ISO code (e.g. 'EUR').
            to_symbol: Three-letter ISO code (e.g. 'USD').
            interval: '1min', '5min', '15min', '30min', '60min'.
            outputsize: 'compact' or 'full'.
            datatype: 'json' or 'csv'.
            month: 'YYYY-MM' for a specific historical month.
        """
        return self._query('FX_INTRADAY',
                           from_symbol=from_symbol, to_symbol=to_symbol, interval=interval,
                           outputsize=outputsize, datatype=datatype, month=month)

    @deserialized(dict)
    def get_fx_daily(self, from_symbol, to_symbol, outputsize=None, datatype=None):
        """function=FX_DAILY — daily OHLC for a currency pair."""
        return self._query('FX_DAILY',
                           from_symbol=from_symbol, to_symbol=to_symbol,
                           outputsize=outputsize, datatype=datatype)

    @deserialized(dict)
    def get_fx_weekly(self, from_symbol, to_symbol, datatype=None):
        """function=FX_WEEKLY — weekly OHLC for a currency pair."""
        return self._query('FX_WEEKLY',
                           from_symbol=from_symbol, to_symbol=to_symbol, datatype=datatype)

    @deserialized(dict)
    def get_fx_monthly(self, from_symbol, to_symbol, datatype=None):
        """function=FX_MONTHLY — monthly OHLC for a currency pair."""
        return self._query('FX_MONTHLY',
                           from_symbol=from_symbol, to_symbol=to_symbol, datatype=datatype)

    def convert_currency(self, amount: float, from_currency: str, to_currency: str) -> dict:
        """Helper — fetch the realtime rate and multiply.

        Returns a dict containing the input, the rate, and the converted amount.
        Useful for quick currency conversion in agent flows.
        """
        rate_response = self.get_exchange_rate(from_currency, to_currency)
        block = rate_response.get('Realtime Currency Exchange Rate', {}) if isinstance(rate_response, dict) else {}
        rate_str = block.get('5. Exchange Rate')
        try:
            rate = float(rate_str) if rate_str is not None else None
        except (TypeError, ValueError):
            rate = None
        converted = (amount * rate) if rate is not None else None
        return {
            'amount': amount,
            'from': from_currency,
            'to': to_currency,
            'rate': rate,
            'converted': converted,
            'last_refreshed': block.get('6. Last Refreshed'),
            'time_zone': block.get('7. Time Zone'),
        }
