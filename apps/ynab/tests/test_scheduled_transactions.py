import pytest
from hamcrest import greater_than_or_equal_to

from apps.ynab.references.web.api.budgets import ApiServiceYNABBudgets
from apps.ynab.references.web.api.scheduled_transactions import ApiServiceYNABScheduledTransactions
from apps.ynab.config import CONFIG


@pytest.fixture()
def given():
    budgets = ApiServiceYNABBudgets(CONFIG)
    budget_id = budgets.get_budgets()['budgets'][0]['id']
    return ApiServiceYNABScheduledTransactions(CONFIG), budget_id


@pytest.mark.smoke
def test_get_scheduled_transactions(given):
    service, budget_id = given
    when = service.get_scheduled_transactions(budget_id)
    then = service.verify.common
    then.assert_that(len(when['scheduled_transactions']), greater_than_or_equal_to(0))


@pytest.mark.skip(reason="destructive — creates/updates/deletes a real scheduled transaction")
def test_scheduled_transaction_crud(given):
    service, budget_id = given
    account_id = '<account-uuid>'  # set before running manually
    body = {"scheduled_transaction": {"account_id": account_id, "date": "2026-07-01",
                                      "amount": -1000, "frequency": "monthly",
                                      "payee_name": "Smoke Test"}}
    created = service.create_scheduled_transaction(budget_id, body)
    st_id = created['scheduled_transaction']['id']
    service.update_scheduled_transaction(budget_id, st_id,
                                         {"scheduled_transaction": {"memo": "updated"}})
    service.delete_scheduled_transaction(budget_id, st_id)
