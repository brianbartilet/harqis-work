from apps.ynab.references.web.base_api_service import BaseApiServiceYouNeedABudget
from core.web.services.core.decorators.deserializer import deserialized


class ApiServiceYNABScheduledTransactions(BaseApiServiceYouNeedABudget):
    """Scheduled (recurring/future) transactions CRUD."""

    def __init__(self, config, **kwargs):
        super(ApiServiceYNABScheduledTransactions, self).__init__(config, **kwargs)
        self.initialize()

    def initialize(self):
        self.request \
            .set_base_uri('budgets')

    @deserialized(dict, child='data')
    def get_scheduled_transactions(self, budget_id):
        self.request.get() \
            .add_uri_parameter(budget_id) \
            .add_uri_parameter('scheduled_transactions')

        return self.client.execute_request(self.request.build())

    @deserialized(dict, child='data')
    def get_scheduled_transaction(self, budget_id, scheduled_transaction_id):
        self.request.get() \
            .add_uri_parameter(budget_id) \
            .add_uri_parameter('scheduled_transactions') \
            .add_uri_parameter(scheduled_transaction_id)

        return self.client.execute_request(self.request.build())

    @deserialized(dict, child='data')
    def create_scheduled_transaction(self, budget_id, scheduled_transaction):
        """Create a scheduled transaction. ``scheduled_transaction`` is the full request
        body, wrapped under ``scheduled_transaction`` per the YNAB API."""
        self.request.post() \
            .add_uri_parameter(budget_id) \
            .add_uri_parameter('scheduled_transactions') \
            .add_json_payload(scheduled_transaction)

        return self.client.execute_request(self.request.build())

    @deserialized(dict, child='data')
    def update_scheduled_transaction(self, budget_id, scheduled_transaction_id, scheduled_transaction):
        """Update a scheduled transaction by id. ``scheduled_transaction`` is the full
        request body, wrapped under ``scheduled_transaction`` per the YNAB API."""
        self.request.put() \
            .add_uri_parameter(budget_id) \
            .add_uri_parameter('scheduled_transactions') \
            .add_uri_parameter(scheduled_transaction_id) \
            .add_json_payload(scheduled_transaction)

        return self.client.execute_request(self.request.build())

    @deserialized(dict, child='data')
    def delete_scheduled_transaction(self, budget_id, scheduled_transaction_id):
        self.request.delete() \
            .add_uri_parameter(budget_id) \
            .add_uri_parameter('scheduled_transactions') \
            .add_uri_parameter(scheduled_transaction_id)

        return self.client.execute_request(self.request.build())
