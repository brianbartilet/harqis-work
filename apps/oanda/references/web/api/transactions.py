from apps.oanda.references.web.base_api_service import BaseApiServiceAppOanda
from core.web.services.core.decorators.deserializer import deserialized


class ApiServiceOandaTransactions(BaseApiServiceAppOanda):

    def __init__(self, config, **kwargs):
        super(ApiServiceOandaTransactions, self).__init__(config, **kwargs)
        self.initialize()

    def initialize(self):
        self.request.set_base_uri('accounts')

    @deserialized(dict)
    def get_transactions(self, account_id, from_time=None, to_time=None,
                         page_size=100, transaction_type=None):
        """GET /accounts/{accountID}/transactions

        Args:
            account_id: OANDA account ID
            from_time: RFC 3339 start time
            to_time: RFC 3339 end time
            page_size: Number of transactions per page (default 100, max 1000)
            transaction_type: Comma-separated list of transaction types to filter
        """
        self.request.get() \
            .add_uri_parameter(account_id) \
            .add_uri_parameter('transactions') \
            .add_query_string('pageSize', page_size)

        if from_time is not None:
            self.request.add_query_string('from', from_time)
        if to_time is not None:
            self.request.add_query_string('to', to_time)
        if transaction_type is not None:
            self.request.add_query_string('type', transaction_type)

        return self.client.execute_request(self.request.build())

    @deserialized(dict, child='transaction')
    def get_transaction(self, account_id, transaction_id):
        """GET /accounts/{accountID}/transactions/{transactionID}

        Args:
            account_id: OANDA account ID
            transaction_id: Transaction ID
        """
        self.request.get() \
            .add_uri_parameter(account_id) \
            .add_uri_parameter('transactions') \
            .add_uri_parameter(transaction_id)

        return self.client.execute_request(self.request.build())

    @deserialized(dict)
    def get_transactions_id_range(self, account_id, from_id, to_id, transaction_type=None):
        """GET /accounts/{accountID}/transactions/idrange

        Args:
            account_id: OANDA account ID
            from_id: Minimum transaction ID (inclusive)
            to_id: Maximum transaction ID (inclusive)
            transaction_type: Comma-separated list of transaction types to filter
        """
        self.request.get() \
            .add_uri_parameter(account_id) \
            .add_uri_parameter('transactions') \
            .add_uri_parameter('idrange') \
            .add_query_string('from', from_id) \
            .add_query_string('to', to_id)

        if transaction_type is not None:
            self.request.add_query_string('type', transaction_type)

        return self.client.execute_request(self.request.build())

    @deserialized(dict)
    def get_transactions_since_id(self, account_id, transaction_id, transaction_type=None):
        """GET /accounts/{accountID}/transactions/sinceid

        Args:
            account_id: OANDA account ID
            transaction_id: Minimum transaction ID (exclusive lower bound)
            transaction_type: Comma-separated list of transaction types to filter
        """
        self.request.get() \
            .add_uri_parameter(account_id) \
            .add_uri_parameter('transactions') \
            .add_uri_parameter('sinceid') \
            .add_query_string('id', transaction_id)

        if transaction_type is not None:
            self.request.add_query_string('type', transaction_type)

        return self.client.execute_request(self.request.build())
