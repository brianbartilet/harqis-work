import pytest
from hamcrest import assert_that, instance_of

from apps.alpha_vantage.config import CONFIG
from apps.alpha_vantage.references.web.api.crypto import ApiServiceAlphaVantageCrypto


@pytest.fixture()
def given():
    return ApiServiceAlphaVantageCrypto(CONFIG)


@pytest.mark.smoke
def test_digital_currency_daily(given):
    when = given.get_digital_currency_daily('BTC', market='USD')
    assert_that(when, instance_of(dict))


@pytest.mark.sanity
def test_crypto_intraday(given):
    when = given.get_crypto_intraday('ETH', market='USD', interval='5min')
    assert_that(when, instance_of(dict))
