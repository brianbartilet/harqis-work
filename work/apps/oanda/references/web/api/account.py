from work.apps.oanda.references.web.base_api_service import BaseApiServiceAppOanda
from work.apps.oanda.references.dto.user_account import DtoAccountProperties, DtoAccountDetails, DtoAccountInstruments
from core.web.services.core.decorators.deserializer import deserialized


class ApiServiceOandaAccount(BaseApiServiceAppOanda):

    def __init__(self, config, **kwargs):
        super(ApiServiceOandaAccount, self).__init__(config, **kwargs)
        self.initialize()

    def initialize(self):
        self.request\
            .add_uri_parameter('v3/accounts')

    @deserialized(list[DtoAccountProperties], child='accounts')
    def get_account_info(self):
        self.request.get()

        return self.client.execute_request(self.request.build())

    #@deserialized(DtoAccountDetails, child='account')
    def get_account_details(self, account_id):
        self.request.get()\
            .add_uri_parameter(account_id)

        return self.client.execute_request(self.request.build())

    #@deserialized(DtoAccountInstruments, child='instruments')
    def get_account_instrument_details(self, account_id, currency_name=None):
        self.request.get() \
            .add_uri_parameter(account_id)\
            .add_uri_parameter('instruments')

        if currency_name is not None:
            self.request \
                .add_query_string('instruments', currency_name)

        return self.client.execute_request(self.request.build())