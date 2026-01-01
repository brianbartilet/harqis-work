import pytest
from hamcrest import equal_to, greater_than_or_equal_to
from apps.ynab.references.web.api.budgets import ApiServiceYNABBudgets
from apps.ynab.config import CONFIG


@pytest.fixture()
def given():
    given_service = ApiServiceYNABBudgets(CONFIG)
    return given_service


@pytest.mark.smoke
def test_get_budgets(given):
    when = given.get_budgets()
    then = given.verify.common
    then.assert_that(len(when['budgets']), greater_than_or_equal_to(0))


@pytest.mark.smoke
def test_get_budget_info(given):
    when_budgets = given.get_budgets()
    budget_id = when_budgets['budgets'][0]['id']

    when = given.get_budget_info(budget_id)
    then = given.verify.common
    then.assert_that(len(when['budget']['id']), equal_to(36))




