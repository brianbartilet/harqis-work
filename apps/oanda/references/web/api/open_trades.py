from apps.oanda.references.web.base_api_service import BaseApiServiceAppOanda
from apps.oanda.references.dto.user_account import DtoAccountProperties
from core.web.services.core.decorators.deserializer import deserialized


class ApiServiceTrades(BaseApiServiceAppOanda):

    def __init__(self, config, **kwargs):
        super(ApiServiceTrades, self).__init__(config, **kwargs)
        self.initialize()

    def initialize(self):
        self.request\
            .set_base_uri('accounts')

    @deserialized(dict, child='trades')
    def get_trades_from_account(self, account_id, **kwargs):

        self.request.get() \
            .add_uri_parameter(account_id) \
            .add_uri_parameter('trades') \
            .add_query_strings(**kwargs)

        return self.client.execute_request(self.request.build())

    @deserialized(dict, child='trades')
    def get_open_trades_from_account(self, account_id):

        self.request.get() \
            .add_uri_parameter(account_id) \
            .add_uri_parameter('openTrades')

        return self.client.execute_request(self.request.build())