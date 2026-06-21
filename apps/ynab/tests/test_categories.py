import pytest
from hamcrest import greater_than_or_equal_to, equal_to

from apps.ynab.references.web.api.budgets import ApiServiceYNABBudgets
from apps.ynab.references.web.api.categories import ApiServiceYNABCategories
from apps.ynab.config import CONFIG


@pytest.fixture()
def given():
    budgets = ApiServiceYNABBudgets(CONFIG)
    budget_id = budgets.get_budgets()['budgets'][0]['id']
    return ApiServiceYNABCategories(CONFIG), budget_id


def _first_category_id(service, budget_id):
    groups = service.get_categories(budget_id)['category_groups']
    for g in groups:
        for c in g.get('categories', []):
            if not c.get('deleted'):
                return c['id']
    return None


@pytest.mark.smoke
def test_get_month_category(given):
    service, budget_id = given
    category_id = _first_category_id(service, budget_id)
    if not category_id:
        pytest.skip("no categories available")
    when = service.get_month_category(budget_id, 'current', category_id)
    then = service.verify.common
    then.assert_that(when['category']['id'], equal_to(category_id))


@pytest.mark.skip(reason="mutating — changes the budgeted amount for a real category/month")
def test_update_month_category(given):
    service, budget_id = given
    category_id = _first_category_id(service, budget_id)
    service.update_month_category(budget_id, 'current', category_id, 0)
