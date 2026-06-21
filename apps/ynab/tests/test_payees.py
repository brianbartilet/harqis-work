import pytest
from hamcrest import greater_than_or_equal_to

from apps.ynab.references.web.api.budgets import ApiServiceYNABBudgets
from apps.ynab.references.web.api.payees import ApiServiceYNABPayees
from apps.ynab.config import CONFIG


@pytest.fixture()
def given():
    budgets = ApiServiceYNABBudgets(CONFIG)
    budget_id = budgets.get_budgets()['budgets'][0]['id']
    return ApiServiceYNABPayees(CONFIG), budget_id


@pytest.mark.smoke
def test_get_payees(given):
    service, budget_id = given
    when = service.get_payees(budget_id)
    then = service.verify.common
    then.assert_that(len(when['payees']), greater_than_or_equal_to(0))
