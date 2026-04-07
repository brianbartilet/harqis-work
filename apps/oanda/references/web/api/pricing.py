from apps.oanda.references.web.base_api_service import BaseApiServiceAppOanda
from core.web.services.core.decorators.deserializer import deserialized


class ApiServiceOandaPricing(BaseApiServiceAppOanda):

    def __init__(self, config, **kwargs):
        super(ApiServiceOandaPricing, self).__init__(config, **kwargs)
        self.initialize()

    def initialize(self):
        self.request.set_base_uri('accounts')

    @deserialized(dict)
    def get_prices(self, account_id, instruments, since_time=None):
        """GET /accounts/{accountID}/pricing

        Args:
            account_id: OANDA account ID
            instruments: Comma-separated instrument list (e.g. 'EUR_USD,USD_JPY')
            since_time: RFC 3339 datetime; only return prices updated since this time
        """
        self.request.get() \
            .add_uri_parameter(account_id) \
            .add_uri_parameter('pricing') \
            .add_query_string('instruments', instruments)

        if since_time is not None:
            self.request.add_query_string('since', since_time)

        return self.client.execute_request(self.request.build())

    @deserialized(dict)
    def get_candles_latest(self, account_id, candle_specifications, units=None):
        """GET /accounts/{accountID}/candles/latest

        Args:
            account_id: OANDA account ID
            candle_specifications: Comma-separated candlestick specs (e.g. 'EUR_USD:S5:BM')
            units: Units traded (affects unit-based specs)
        """
        self.request.get() \
            .add_uri_parameter(account_id) \
            .add_uri_parameter('candles') \
            .add_uri_parameter('latest') \
            .add_query_string('candleSpecifications', candle_specifications)

        if units is not None:
            self.request.add_query_string('units', units)

        return self.client.execute_request(self.request.build())

    @deserialized(dict)
    def get_instrument_candles(self, account_id, instrument, granularity='S5', count=500,
                               from_time=None, to_time=None, price='M'):
        """GET /accounts/{accountID}/instruments/{instrument}/candles

        Args:
            account_id: OANDA account ID
            instrument: Instrument name (e.g. 'EUR_USD')
            granularity: Candlestick granularity (S5, M1, H1, D, etc.) Default S5
            count: Number of candles to return (max 5000). Default 500
            from_time: RFC 3339 start time
            to_time: RFC 3339 end time
            price: Bid/Ask/Mid pricing component ('M', 'B', 'A', 'BA', 'MBA'). Default 'M'
        """
        self.request.get() \
            .add_uri_parameter(account_id) \
            .add_uri_parameter('instruments') \
            .add_uri_parameter(instrument) \
            .add_uri_parameter('candles') \
            .add_query_string('granularity', granularity) \
            .add_query_string('price', price)

        if from_time is not None:
            self.request.add_query_string('from', from_time)
        elif to_time is not None:
            self.request.add_query_string('to', to_time)
        else:
            self.request.add_query_string('count', count)

        return self.client.execute_request(self.request.build())
