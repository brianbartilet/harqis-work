import pytest
from hamcrest import greater_than_or_equal_to

from apps.ynab.references.web.api.budgets import ApiServiceYNABBudgets
from apps.ynab.references.web.api.months import ApiServiceYNABMonths
from apps.ynab.config import CONFIG


@pytest.fixture()
def given():
    budgets = ApiServiceYNABBudgets(CONFIG)
    budget_id = budgets.get_budgets()['budgets'][0]['id']
    return ApiServiceYNABMonths(CONFIG), budget_id


@pytest.mark.smoke
def test_get_months(given):
    service, budget_id = given
    when = service.get_months(budget_id)
    then = service.verify.common
    then.assert_that(len(when['months']), greater_than_or_equal_to(0))


@pytest.mark.smoke
def test_get_month_current(given):
    service, budget_id = given
    when = service.get_month(budget_id, 'current')
    then = service.verify.common
    then.assert_that(len(when['month'].get('categories', [])), greater_than_or_equal_to(0))
