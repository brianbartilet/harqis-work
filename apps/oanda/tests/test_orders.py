import pytest
from hamcrest import assert_that, instance_of, greater_than_or_equal_to

from apps.oanda.config import CONFIG
from apps.oanda.references.web.api.account import ApiServiceOandaAccount
from apps.oanda.references.web.api.orders import ApiServiceOandaOrders


@pytest.fixture()
def given_account_id():
    service = ApiServiceOandaAccount(CONFIG)
    accounts = service.get_account_info()
    return accounts[0].id


@pytest.fixture()
def given_orders_service():
    return ApiServiceOandaOrders(CONFIG)


@pytest.mark.smoke
def test_get_orders(given_orders_service, given_account_id):
    when = given_orders_service.get_orders(given_account_id)
    assert_that(when, instance_of(list))


@pytest.mark.smoke
def test_get_pending_orders(given_orders_service, given_account_id):
    when = given_orders_service.get_pending_orders(given_account_id)
    assert_that(when, instance_of(list))
