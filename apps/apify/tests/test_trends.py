"""
Live integration tests for the trends helpers.

These tests call public Apify actors which consume compute units. They are
marked ``sanity`` (not ``smoke``) so they don't run on every quick check.
"""
import pytest
from hamcrest import any_of, assert_that, instance_of

from apps.apify.config import CONFIG
from apps.apify.references.web.api.trends import ApiServiceApifyTrends, DEFAULT_ACTORS


@pytest.fixture()
def trends():
    return ApiServiceApifyTrends(CONFIG)


def test_default_actors_are_strings():
    for platform, actor_id in DEFAULT_ACTORS.items():
        assert isinstance(platform, str) and platform
        assert isinstance(actor_id, str) and '/' in actor_id


@pytest.mark.sanity
def test_search_google_trends(trends):
    result = trends.search_google_trends(['AI'], geo='US', timeframe='today 1-m')
    assert_that(result, any_of(instance_of(list), instance_of(dict)))


@pytest.mark.sanity
def test_search_reddit(trends):
    result = trends.search_reddit(['python'], max_items=5)
    assert_that(result, any_of(instance_of(list), instance_of(dict)))


@pytest.mark.sanity
def test_aggregate_trends_single_platform(trends):
    result = trends.aggregate_trends('AI', platforms=['reddit'], per_platform_limit=3)
    assert_that(result, instance_of(list))
