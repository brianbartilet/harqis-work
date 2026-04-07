from typing import List

from apps.oanda.references.web.base_api_service import BaseApiServiceAppOanda
from apps.oanda.references.dto.user_account import DtoAccountProperties, DtoAccountDetails, DtoAccountInstruments
from core.web.services.core.decorators.deserializer import deserialized


class ApiServiceOandaAccount(BaseApiServiceAppOanda):

    def __init__(self, config, **kwargs):
        super(ApiServiceOandaAccount, self).__init__(config, **kwargs)
        self.initialize()

    def initialize(self):
        self.request.set_base_uri('accounts')

    @deserialized(List[DtoAccountProperties], child='accounts', many=True)
    def get_account_info(self):
        """GET /accounts — list all accounts."""
        self.request.get()
        return self.client.execute_request(self.request.build())

    @deserialized(DtoAccountDetails, child='account')
    def get_account_details(self, account_id):
        """GET /accounts/{accountID} — full account details."""
        self.request.get() \
            .add_uri_parameter(account_id)
        return self.client.execute_request(self.request.build())

    @deserialized(DtoAccountInstruments, child='instruments')
    def get_account_instrument_details(self, account_id, currency_name=None):
        """GET /accounts/{accountID}/instruments — tradeable instruments.

        Args:
            account_id: OANDA account ID
            currency_name: Optional comma-separated instrument filter (e.g. 'EUR_USD,USD_JPY')
        """
        self.request.get() \
            .add_uri_parameter(account_id) \
            .add_uri_parameter('instruments')

        if currency_name is not None:
            self.request.add_query_string('instruments', currency_name)

        return self.client.execute_request(self.request.build())

    @deserialized(dict, child='account')
    def get_account_summary(self, account_id):
        """GET /accounts/{accountID}/summary — lightweight account summary.

        Args:
            account_id: OANDA account ID
        """
        self.request.get() \
            .add_uri_parameter(account_id) \
            .add_uri_parameter('summary')

        return self.client.execute_request(self.request.build())

    @deserialized(dict)
    def get_account_changes(self, account_id, since_transaction_id):
        """GET /accounts/{accountID}/changes — changes since a transaction ID.

        Args:
            account_id: OANDA account ID
            since_transaction_id: Transaction ID to poll changes since
        """
        self.request.get() \
            .add_uri_parameter(account_id) \
            .add_uri_parameter('changes') \
            .add_query_string('sinceTransactionID', since_transaction_id)

        return self.client.execute_request(self.request.build())

    @deserialized(dict)
    def configure_account(self, account_id, alias=None, margin_rate=None):
        """PATCH /accounts/{accountID}/configuration — update account configuration.

        Args:
            account_id: OANDA account ID
            alias: New account alias
            margin_rate: New margin rate (e.g. '0.02' for 2%)
        """
        body = {}
        if alias is not None:
            body['alias'] = alias
        if margin_rate is not None:
            body['marginRate'] = margin_rate

        self.request.patch() \
            .add_uri_parameter(account_id) \
            .add_uri_parameter('configuration') \
            .add_json_payload(body)

        return self.client.execute_request(self.request.build())
