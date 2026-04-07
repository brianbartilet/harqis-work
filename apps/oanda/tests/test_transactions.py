import pytest
from hamcrest import assert_that, has_key, instance_of

from apps.oanda.config import CONFIG
from apps.oanda.references.web.api.account import ApiServiceOandaAccount
from apps.oanda.references.web.api.transactions import ApiServiceOandaTransactions


@pytest.fixture()
def given_account_id():
    service = ApiServiceOandaAccount(CONFIG)
    accounts = service.get_account_info()
    return accounts[0].id


@pytest.fixture()
def given_transactions_service():
    return ApiServiceOandaTransactions(CONFIG)


@pytest.mark.smoke
def test_get_transactions(given_transactions_service, given_account_id):
    when = given_transactions_service.get_transactions(given_account_id, page_size=10)
    assert_that(when, has_key('pages'))


@pytest.mark.smoke
def test_get_transactions_since_id(given_transactions_service, given_account_id):
    # Get the latest transaction ID from the account changes endpoint
    service = ApiServiceOandaTransactions(CONFIG)
    result = service.get_transactions(given_account_id, page_size=1)
    assert_that(result, has_key('lastTransactionID'))
