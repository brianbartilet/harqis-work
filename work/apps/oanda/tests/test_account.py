import pytest

from work.apps.oanda.references.web.api.account import ApiServiceOandaAccount
from work.apps.oanda.config import CONFIG


@pytest.fixture()
def given_service_account():
    given_service = ApiServiceOandaAccount(CONFIG)
    return given_service


@pytest.mark.sanity  # Mark the test as a sanity test
def test_service_account(given_service_account):
    when = given_service_account.get_account_info()
    account = when[0].mt4AccountID
    then = given_service_account.verify.common
    then.assert_that(True, isinstance(account, int))

