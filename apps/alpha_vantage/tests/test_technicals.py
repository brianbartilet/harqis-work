import pytest
from hamcrest import assert_that, instance_of

from apps.alpha_vantage.config import CONFIG
from apps.alpha_vantage.references.web.api.technicals import ApiServiceAlphaVantageTechnicals


@pytest.fixture()
def given():
    return ApiServiceAlphaVantageTechnicals(CONFIG)


@pytest.mark.smoke
def test_rsi(given):
    when = given.rsi('IBM', interval='daily', time_period=14)
    assert_that(when, instance_of(dict))


@pytest.mark.smoke
def test_sma(given):
    when = given.sma('IBM', interval='daily', time_period=20)
    assert_that(when, instance_of(dict))


@pytest.mark.sanity
def test_macd(given):
    when = given.macd('IBM', interval='daily')
    assert_that(when, instance_of(dict))


@pytest.mark.sanity
def test_get_indicator_generic(given):
    when = given.get_indicator('EMA', 'IBM', interval='daily', time_period=10, series_type='close')
    assert_that(when, instance_of(dict))
