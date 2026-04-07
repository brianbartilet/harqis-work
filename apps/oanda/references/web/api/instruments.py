from apps.oanda.references.web.base_api_service import BaseApiServiceAppOanda
from core.web.services.core.decorators.deserializer import deserialized


class ApiServiceOandaInstruments(BaseApiServiceAppOanda):
    """Instrument-scoped endpoints (not account-scoped)."""

    def __init__(self, config, **kwargs):
        super(ApiServiceOandaInstruments, self).__init__(config, **kwargs)
        self.initialize()

    def initialize(self):
        self.request.set_base_uri('instruments')

    @deserialized(dict)
    def get_candles(self, instrument, granularity='S5', count=500,
                    from_time=None, to_time=None, price='M',
                    smooth=False, include_first=True):
        """GET /instruments/{instrument}/candles

        Args:
            instrument: Instrument name (e.g. 'EUR_USD')
            granularity: Candlestick granularity (S5, M1, M5, M15, M30, H1, H4, D, W, M)
            count: Number of candles (max 5000). Default 500
            from_time: RFC 3339 start time
            to_time: RFC 3339 end time
            price: Pricing component ('M'=mid, 'B'=bid, 'A'=ask, 'BA', 'MBA'). Default 'M'
            smooth: Whether to use smooth candles. Default False
            include_first: Include the first candlestick in the response. Default True
        """
        self.request.get() \
            .add_uri_parameter(instrument) \
            .add_uri_parameter('candles') \
            .add_query_string('granularity', granularity) \
            .add_query_string('price', price) \
            .add_query_string('smooth', str(smooth).lower())

        if from_time is not None:
            self.request \
                .add_query_string('from', from_time) \
                .add_query_string('includeFirst', str(include_first).lower())
            if to_time is not None:
                self.request.add_query_string('to', to_time)
        elif to_time is not None:
            self.request.add_query_string('to', to_time)
        else:
            self.request.add_query_string('count', count)

        return self.client.execute_request(self.request.build())

    @deserialized(dict)
    def get_order_book(self, instrument, time=None):
        """GET /instruments/{instrument}/orderBook

        Args:
            instrument: Instrument name (e.g. 'EUR_USD')
            time: RFC 3339 datetime for snapshot (omit for latest)
        """
        self.request.get() \
            .add_uri_parameter(instrument) \
            .add_uri_parameter('orderBook')

        if time is not None:
            self.request.add_query_string('time', time)

        return self.client.execute_request(self.request.build())

    @deserialized(dict)
    def get_position_book(self, instrument, time=None):
        """GET /instruments/{instrument}/positionBook

        Args:
            instrument: Instrument name (e.g. 'EUR_USD')
            time: RFC 3339 datetime for snapshot (omit for latest)
        """
        self.request.get() \
            .add_uri_parameter(instrument) \
            .add_uri_parameter('positionBook')

        if time is not None:
            self.request.add_query_string('time', time)

        return self.client.execute_request(self.request.build())
