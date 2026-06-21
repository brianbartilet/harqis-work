from apps.ynab.references.web.base_api_service import BaseApiServiceYouNeedABudget
from core.web.services.core.decorators.deserializer import deserialized


class ApiServiceYNABMonths(BaseApiServiceYouNeedABudget):
    """Budget months — the monthly plan (budgeted/activity/balance per category)."""

    def __init__(self, config, **kwargs):
        super(ApiServiceYNABMonths, self).__init__(config, **kwargs)
        self.initialize()

    def initialize(self):
        self.request \
            .set_base_uri('budgets')

    @deserialized(dict, child='data')
    def get_months(self, budget_id):
        """List all budget months (summary of the plan for each month)."""
        self.request.get() \
            .add_uri_parameter(budget_id) \
            .add_uri_parameter('months')

        return self.client.execute_request(self.request.build())

    @deserialized(dict, child='data')
    def get_month(self, budget_id, month):
        """Get the full plan for a single month, including all category budgeted amounts.

        Args:
            month: Budget month in ISO format (e.g. '2026-06-01') or 'current'.
        """
        self.request.get() \
            .add_uri_parameter(budget_id) \
            .add_uri_parameter('months') \
            .add_uri_parameter(month)

        return self.client.execute_request(self.request.build())
