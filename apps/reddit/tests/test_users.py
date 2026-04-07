import pytest
from hamcrest import assert_that, instance_of, has_key, not_none

from apps.reddit.references.web.api.users import ApiServiceRedditUsers
from apps.reddit.config import CONFIG


def _require_credentials():
    if not CONFIG.app_data.get('client_id'):
        pytest.skip("REDDIT_CLIENT_ID not configured in .env/apps.env")


@pytest.fixture()
def given():
    _require_credentials()
    return ApiServiceRedditUsers(CONFIG)


@pytest.mark.smoke
def test_get_me(given):
    """Authenticated user profile is reachable — confirms token is valid."""
    when = given.get_me()
    assert_that(when, instance_of(dict))
    assert_that(when, has_key('name'))
    assert_that(when, has_key('total_karma'))
    assert_that(when.get('name'), not_none())


@pytest.mark.sanity
def test_get_karma(given):
    """Returns karma breakdown by subreddit."""
    when = given.get_karma()
    assert_that(when, instance_of(dict))
    assert_that(when, has_key('data'))


@pytest.mark.sanity
def test_get_user_profile(given):
    """Fetches authenticated user's own public profile by username."""
    me = ApiServiceRedditUsers(CONFIG).get_me()
    username = me.get('name')
    if not username:
        pytest.skip("Could not retrieve username from /api/v1/me")
    when = ApiServiceRedditUsers(CONFIG).get_user(username)
    assert_that(when, instance_of(dict))
    assert_that(when, has_key('kind'))
    assert_that(when.get('data', {}).get('name'), not_none())


@pytest.mark.sanity
def test_get_inbox(given):
    """Inbox endpoint is reachable."""
    when = given.get_inbox(limit=5)
    assert_that(when, instance_of(dict))
    assert_that(when, has_key('data'))
