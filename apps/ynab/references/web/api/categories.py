from apps.ynab.references.web.base_api_service import BaseApiServiceYouNeedABudget
from core.web.services.core.decorators.deserializer import deserialized


class ApiServiceYNABCategories(BaseApiServiceYouNeedABudget):
    """Category lookups, including month-specific budgeted amounts (the monthly plan)."""

    def __init__(self, config, **kwargs):
        super(ApiServiceYNABCategories, self).__init__(config, **kwargs)
        self.initialize()

    def initialize(self):
        self.request \
            .set_base_uri('budgets')

    @deserialized(dict, child='data')
    def get_categories(self, budget_id):
        self.request.get() \
            .add_uri_parameter(budget_id) \
            .add_uri_parameter('categories')

        return self.client.execute_request(self.request.build())

    @deserialized(dict, child='data')
    def get_category(self, budget_id, category_id):
        self.request.get() \
            .add_uri_parameter(budget_id) \
            .add_uri_parameter('categories') \
            .add_uri_parameter(category_id)

        return self.client.execute_request(self.request.build())

    @deserialized(dict, child='data')
    def get_month_category(self, budget_id, month, category_id):
        """Get a single category's data for a specific month.

        Args:
            month: Budget month in ISO format (e.g. '2026-06-01') or 'current'.
        """
        self.request.get() \
            .add_uri_parameter(budget_id) \
            .add_uri_parameter('months') \
            .add_uri_parameter(month) \
            .add_uri_parameter('categories') \
            .add_uri_parameter(category_id)

        return self.client.execute_request(self.request.build())

    @deserialized(dict, child='data')
    def update_month_category(self, budget_id, month, category_id, budgeted):
        """Update a category's budgeted amount for a specific month.

        Args:
            month: Budget month in ISO format (e.g. '2026-06-01') or 'current'.
            budgeted: Budgeted amount in milliunits (the only assignable month field).
        """
        payload = {'category': {'budgeted': budgeted}}

        self.request.patch() \
            .add_uri_parameter(budget_id) \
            .add_uri_parameter('months') \
            .add_uri_parameter(month) \
            .add_uri_parameter('categories') \
            .add_uri_parameter(category_id) \
            .add_json_payload(payload)

        return self.client.execute_request(self.request.build())
