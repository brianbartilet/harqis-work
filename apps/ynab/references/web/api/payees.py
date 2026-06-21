from apps.ynab.references.web.base_api_service import BaseApiServiceYouNeedABudget
from core.web.services.core.decorators.deserializer import deserialized


class ApiServiceYNABPayees(BaseApiServiceYouNeedABudget):

    def __init__(self, config, **kwargs):
        super(ApiServiceYNABPayees, self).__init__(config, **kwargs)
        self.initialize()

    def initialize(self):
        self.request \
            .set_base_uri('budgets')

    @deserialized(dict, child='data')
    def get_payees(self, budget_id):
        self.request.get() \
            .add_uri_parameter(budget_id) \
            .add_uri_parameter('payees')

        return self.client.execute_request(self.request.build())

    @deserialized(dict, child='data')
    def get_payee(self, budget_id, payee_id):
        self.request.get() \
            .add_uri_parameter(budget_id) \
            .add_uri_parameter('payees') \
            .add_uri_parameter(payee_id)

        return self.client.execute_request(self.request.build())
