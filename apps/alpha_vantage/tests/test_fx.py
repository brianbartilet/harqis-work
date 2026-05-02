import pytest
from hamcrest import assert_that, instance_of, has_key, not_none

from apps.alpha_vantage.config import CONFIG
from apps.alpha_vantage.references.web.api.fx import ApiServiceAlphaVantageFx


@pytest.fixture()
def given():
    return ApiServiceAlphaVantageFx(CONFIG)


@pytest.mark.smoke
def test_exchange_rate(given):
    when = given.get_exchange_rate('USD', 'EUR')
    assert_that(when, instance_of(dict))
    assert_that(when, has_key('Realtime Currency Exchange Rate'))


@pytest.mark.smoke
def test_convert_currency(given):
    when = given.convert_currency(100, 'USD', 'EUR')
    assert_that(when, instance_of(dict))
    assert_that(when['from'], not_none())
    assert_that(when['to'], not_none())


@pytest.mark.sanity
def test_fx_daily(given):
    when = given.get_fx_daily('EUR', 'USD', outputsize='compact')
    assert_that(when, instance_of(dict))
