from apps.oanda.references.web.base_api_service import BaseApiServiceAppOanda
from core.web.services.core.decorators.deserializer import deserialized


class ApiServiceOandaPositions(BaseApiServiceAppOanda):

    def __init__(self, config, **kwargs):
        super(ApiServiceOandaPositions, self).__init__(config, **kwargs)
        self.initialize()

    def initialize(self):
        self.request.set_base_uri('accounts')

    @deserialized(dict, child='positions')
    def get_positions(self, account_id):
        """GET /accounts/{accountID}/positions

        Args:
            account_id: OANDA account ID
        """
        self.request.get() \
            .add_uri_parameter(account_id) \
            .add_uri_parameter('positions')

        return self.client.execute_request(self.request.build())

    @deserialized(dict, child='positions')
    def get_open_positions(self, account_id):
        """GET /accounts/{accountID}/openPositions

        Args:
            account_id: OANDA account ID
        """
        self.request.get() \
            .add_uri_parameter(account_id) \
            .add_uri_parameter('openPositions')

        return self.client.execute_request(self.request.build())

    @deserialized(dict, child='position')
    def get_position(self, account_id, instrument):
        """GET /accounts/{accountID}/positions/{instrument}

        Args:
            account_id: OANDA account ID
            instrument: Instrument name (e.g. 'EUR_USD')
        """
        self.request.get() \
            .add_uri_parameter(account_id) \
            .add_uri_parameter('positions') \
            .add_uri_parameter(instrument)

        return self.client.execute_request(self.request.build())

    @deserialized(dict)
    def close_position(self, account_id, instrument, long_units=None, short_units=None):
        """PUT /accounts/{accountID}/positions/{instrument}/close

        Args:
            account_id: OANDA account ID
            instrument: Instrument name (e.g. 'EUR_USD')
            long_units: Units of long position to close ('ALL' or number string)
            short_units: Units of short position to close ('ALL' or number string)
        """
        body = {}
        if long_units is not None:
            body['longUnits'] = long_units
        if short_units is not None:
            body['shortUnits'] = short_units

        self.request.put() \
            .add_uri_parameter(account_id) \
            .add_uri_parameter('positions') \
            .add_uri_parameter(instrument) \
            .add_uri_parameter('close') \
            .add_json_payload(body)

        return self.client.execute_request(self.request.build())
