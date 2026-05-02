import pytest
from hamcrest import assert_that, instance_of, has_key

from apps.alpha_vantage.config import CONFIG
from apps.alpha_vantage.references.web.api.core_stock import ApiServiceAlphaVantageCoreStock


@pytest.fixture()
def given():
    return ApiServiceAlphaVantageCoreStock(CONFIG)


@pytest.mark.smoke
def test_global_quote(given):
    when = given.get_global_quote('IBM')
    assert_that(when, instance_of(dict))
    assert_that(when, has_key('Global Quote'))


@pytest.mark.smoke
def test_search_symbol(given):
    when = given.search_symbol('tesla')
    assert_that(when, instance_of(dict))


@pytest.mark.smoke
def test_market_status(given):
    when = given.get_market_status()
    assert_that(when, instance_of(dict))


@pytest.mark.sanity
def test_intraday(given):
    when = given.get_intraday('IBM', interval='5min', outputsize='compact')
    assert_that(when, instance_of(dict))


@pytest.mark.sanity
def test_daily(given):
    when = given.get_daily('IBM', outputsize='compact')
    assert_that(when, instance_of(dict))
