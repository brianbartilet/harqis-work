import pytest

from core.utilities.data.qlist import QList
from hamcrest import greater_than, equal_to, greater_than_or_equal_to

from apps.oanda.references.web.api.account import ApiServiceOandaAccount
from apps.oanda.config import CONFIG


@pytest.fixture()
def given_service_account():
    given_service = ApiServiceOandaAccount(CONFIG)
    return given_service


@pytest.mark.smoke
def test_service_account(given_service_account):
    when = given_service_account.get_account_info()
    when_account = when[0].mt4AccountID
    then = given_service_account.verify.common
    then.assert_that(when_account, greater_than(0))


@pytest.mark.smoke
def test_service_account_details(given_service_account):
    given = given_service_account.get_account_info()
    given_id = given[0].id
    when_get_account_details = given_service_account.get_account_details(given_id)
    then = given_service_account.verify.common
    then.assert_that(when_get_account_details.openTradeCount, greater_than_or_equal_to(0))


