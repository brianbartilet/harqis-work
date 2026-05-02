import pytest
from hamcrest import assert_that, instance_of

from apps.alpha_vantage.config import CONFIG
from apps.alpha_vantage.references.web.api.fundamentals import ApiServiceAlphaVantageFundamentals


@pytest.fixture()
def given():
    return ApiServiceAlphaVantageFundamentals(CONFIG)


@pytest.mark.smoke
def test_overview(given):
    when = given.get_overview('IBM')
    assert_that(when, instance_of(dict))


@pytest.mark.sanity
def test_income_statement(given):
    when = given.get_income_statement('IBM')
    assert_that(when, instance_of(dict))


@pytest.mark.sanity
def test_earnings(given):
    when = given.get_earnings('IBM')
    assert_that(when, instance_of(dict))
