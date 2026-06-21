import pytest
from hamcrest import greater_than_or_equal_to, equal_to

from apps.ynab.references.web.api.budgets import ApiServiceYNABBudgets
from apps.ynab.references.web.api.transactions import ApiServiceYNABTransactions
from apps.ynab.config import CONFIG


@pytest.fixture()
def given():
    budgets = ApiServiceYNABBudgets(CONFIG)
    budget_id = budgets.get_budgets()['budgets'][0]['id']
    return ApiServiceYNABTransactions(CONFIG), budget_id


@pytest.mark.smoke
def test_get_transactions(given):
    service, budget_id = given
    when = service.get_transactions(budget_id)
    then = service.verify.common
    then.assert_that(len(when['transactions']), greater_than_or_equal_to(0))


@pytest.mark.smoke
def test_get_transaction(given):
    service, budget_id = given
    transactions = service.get_transactions(budget_id)['transactions']
    if not transactions:
        pytest.skip("no transactions to fetch")
    tx_id = transactions[0]['id']
    when = service.get_transaction(budget_id, tx_id)
    then = service.verify.common
    then.assert_that(when['transaction']['id'], equal_to(tx_id))


@pytest.mark.skip(reason="destructive — creates/updates/deletes a real transaction")
def test_transaction_crud(given):
    service, budget_id = given
    account_id = '<account-uuid>'  # set before running manually
    body = {"transaction": {"account_id": account_id, "date": "2026-06-21", "amount": -1000,
                            "payee_name": "Smoke Test", "approved": True}}
    created = service.create_new_transaction(budget_id, body)
    tx_id = created['transaction']['id']
    service.update_transaction(budget_id, tx_id, {"transaction": {"memo": "updated"}})
    service.delete_transaction(budget_id, tx_id)
