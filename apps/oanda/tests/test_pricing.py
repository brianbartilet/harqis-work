import pytest
from hamcrest import assert_that, has_key, greater_than_or_equal_to, instance_of

from apps.oanda.config import CONFIG
from apps.oanda.references.web.api.account import ApiServiceOandaAccount
from apps.oanda.references.web.api.pricing import ApiServiceOandaPricing


@pytest.fixture()
def given_account_id():
    service = ApiServiceOandaAccount(CONFIG)
    accounts = service.get_account_info()
    return accounts[0].id


@pytest.fixture()
def given_pricing_service():
    return ApiServiceOandaPricing(CONFIG)


@pytest.mark.smoke
def test_get_prices(given_pricing_service, given_account_id):
    when = given_pricing_service.get_prices(given_account_id, instruments='EUR_USD')
    assert_that(when, has_key('prices'))


@pytest.mark.smoke
def test_get_instrument_candles(given_pricing_service, given_account_id):
    when = given_pricing_service.get_instrument_candles(
        given_account_id, instrument='EUR_USD', granularity='H1', count=10
    )
    assert_that(when, has_key('candles'))
