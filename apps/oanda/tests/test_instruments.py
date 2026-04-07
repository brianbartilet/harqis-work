import pytest
from hamcrest import assert_that, has_key, instance_of

from apps.oanda.config import CONFIG
from apps.oanda.references.web.api.instruments import ApiServiceOandaInstruments


@pytest.fixture()
def given_instruments_service():
    return ApiServiceOandaInstruments(CONFIG)


@pytest.mark.smoke
def test_get_candles(given_instruments_service):
    when = given_instruments_service.get_candles('EUR_USD', granularity='H1', count=10)
    assert_that(when, has_key('candles'))


@pytest.mark.skip(reason="Order book endpoint requires elevated OANDA API access (returns 401 on standard accounts)")
def test_get_order_book(given_instruments_service):
    when = given_instruments_service.get_order_book('EUR_USD')
    assert_that(when, has_key('orderBook'))


@pytest.mark.skip(reason="Position book endpoint requires elevated OANDA API access (returns 401 on standard accounts)")
def test_get_position_book(given_instruments_service):
    when = given_instruments_service.get_position_book('EUR_USD')
    assert_that(when, has_key('positionBook'))
