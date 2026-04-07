import pytest
from hamcrest import assert_that, instance_of

from apps.oanda.config import CONFIG
from apps.oanda.references.web.api.account import ApiServiceOandaAccount
from apps.oanda.references.web.api.positions import ApiServiceOandaPositions


@pytest.fixture()
def given_account_id():
    service = ApiServiceOandaAccount(CONFIG)
    accounts = service.get_account_info()
    return accounts[0].id


@pytest.fixture()
def given_positions_service():
    return ApiServiceOandaPositions(CONFIG)


@pytest.mark.smoke
def test_get_positions(given_positions_service, given_account_id):
    when = given_positions_service.get_positions(given_account_id)
    assert_that(when, instance_of(list))


@pytest.mark.smoke
def test_get_open_positions(given_positions_service, given_account_id):
    when = given_positions_service.get_open_positions(given_account_id)
    assert_that(when, instance_of(list))
