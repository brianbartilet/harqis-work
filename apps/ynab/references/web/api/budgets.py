from apps.ynab.references.web.base_api_service import BaseApiServiceYouNeedABudget
from core.web.services.core.decorators.deserializer import deserialized


class ApiServiceYNABBudgets(BaseApiServiceYouNeedABudget):

    def __init__(self, config, **kwargs):
        super(ApiServiceYNABBudgets, self).__init__(config, **kwargs)
        self.initialize()

    def initialize(self):
        self.request \
            .set_base_uri('budgets')

    @deserialized(dict, child='data')
    def get_accounts(self, budget_id: str):
        self.request.get() \
            .add_uri_parameter(budget_id) \
            .add_uri_parameter('accounts')

        return self.client.execute_request(self.request.build())

    @deserialized(dict, child='data')
    def get_budgets(self):
        self.request.get()

        return self.client.execute_request(self.request.build())

    @deserialized(dict, child='data')
    def get_budget_info(self, budget_id: str):
        self.request.get() \
            .add_uri_parameter(budget_id)

        return self.client.execute_request(self.request.build())

    @deserialized(dict, child='data')
    def get_categories(self, budget_id):
        self.request.get() \
            .add_uri_parameter(budget_id) \
            .add_uri_parameter('categories')

        return self.client.execute_request(self.request.build())


