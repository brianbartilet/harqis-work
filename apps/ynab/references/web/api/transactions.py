from apps.ynab.references.web.base_api_service import BaseApiServiceYouNeedABudget
from apps.ynab.references.dto.transaction import DtoSaveTransaction, DtoUpdateTransaction
from core.web.services.core.decorators.deserializer import deserialized


class ApiServiceYNABTransactions(BaseApiServiceYouNeedABudget):

    def __init__(self, config, **kwargs):
        super(ApiServiceYNABTransactions, self).__init__(config, **kwargs)
        self.initialize()

    def initialize(self):
        self.request \
            .set_base_uri('budgets')

    @deserialized(dict, child='data')
    def get_transactions(self, budget_id):
        self.request.get() \
            .add_uri_parameter(budget_id) \
            .add_uri_parameter('transactions')

        return self.client.execute_request(self.request.build())

    @deserialized(dict, child='data')
    def get_transactions_per_account(self, budget_id, account_id):
        self.request.get() \
            .add_uri_parameter(budget_id)\
            .add_uri_parameter('accounts')\
            .add_uri_parameter(account_id)\
            .add_uri_parameter('transactions')

        return self.client.execute_request(self.request.build())

    @deserialized(dict, child='data')
    def get_transaction(self, budget_id, transaction_id):
        self.request.get() \
            .add_uri_parameter(budget_id)\
            .add_uri_parameter('transactions')\
            .add_uri_parameter(transaction_id)

        return self.client.execute_request(self.request.build())

    @deserialized(dict, child='data')
    def create_new_transaction(self, budget_id, transaction):
        """Create a transaction. ``transaction`` is the full request body, wrapped under
        ``transaction`` (single) or ``transactions`` (bulk) per the YNAB API."""
        self.request.post() \
            .add_uri_parameter(budget_id)\
            .add_uri_parameter('transactions')\
            .add_json_payload(transaction)

        return self.client.execute_request(self.request.build())

    @deserialized(dict, child='data')
    def update_transaction(self, budget_id, transaction_id, transaction):
        """Update a single transaction by id. ``transaction`` is the full request body,
        wrapped under ``transaction`` per the YNAB API."""
        self.request.put() \
            .add_uri_parameter(budget_id)\
            .add_uri_parameter('transactions')\
            .add_uri_parameter(transaction_id)\
            .add_json_payload(transaction)

        return self.client.execute_request(self.request.build())

    @deserialized(dict, child='data')
    def delete_transaction(self, budget_id, transaction_id):
        self.request.delete() \
            .add_uri_parameter(budget_id)\
            .add_uri_parameter('transactions')\
            .add_uri_parameter(transaction_id)

        return self.client.execute_request(self.request.build())

