import pytest
from hamcrest import assert_that, instance_of

from apps.alpha_vantage.config import CONFIG
from apps.alpha_vantage.references.web.api.news import ApiServiceAlphaVantageNews


@pytest.fixture()
def given():
    return ApiServiceAlphaVantageNews(CONFIG)


@pytest.mark.smoke
def test_news_sentiment(given):
    when = given.get_news_sentiment(tickers='AAPL', limit=10)
    assert_that(when, instance_of(dict))


@pytest.mark.smoke
def test_top_gainers_losers(given):
    when = given.get_top_gainers_losers()
    assert_that(when, instance_of(dict))


@pytest.mark.sanity
def test_insider_transactions(given):
    when = given.get_insider_transactions('IBM')
    assert_that(when, instance_of(dict))
