import pytest
from hamcrest import assert_that, instance_of, has_key, greater_than_or_equal_to, not_none

from apps.reddit.references.web.api.subreddits import ApiServiceRedditSubreddits
from apps.reddit.config import CONFIG


def _require_credentials():
    if not CONFIG.app_data.get('client_id'):
        pytest.skip("REDDIT_CLIENT_ID not configured in .env/apps.env")


@pytest.fixture()
def given():
    _require_credentials()
    return ApiServiceRedditSubreddits(CONFIG)


@pytest.fixture()
def default_subreddit():
    _require_credentials()
    return CONFIG.app_data.get('default_subreddit', 'python')


@pytest.mark.smoke
def test_get_subreddit_info(given, default_subreddit):
    """Fetches subreddit metadata — confirms auth and API connectivity."""
    when = given.get_info(default_subreddit)
    assert_that(when, instance_of(dict))
    assert_that(when, has_key('kind'))
    data = when.get('data', {})
    assert_that(data, has_key('display_name'))
    assert_that(data, has_key('subscribers'))


@pytest.mark.smoke
def test_get_hot_posts(given, default_subreddit):
    """Returns hot posts listing from a subreddit."""
    when = given.get_posts(default_subreddit, sort='hot', limit=10)
    assert_that(when, instance_of(dict))
    children = when.get('data', {}).get('children', [])
    assert_that(children, instance_of(list))
    assert_that(len(children), greater_than_or_equal_to(0))


@pytest.mark.sanity
def test_get_new_posts(given, default_subreddit):
    """Returns new posts listing."""
    when = given.get_posts(default_subreddit, sort='new', limit=5)
    assert_that(when, instance_of(dict))
    assert_that(when.get('data'), not_none())


@pytest.mark.sanity
def test_search_posts(given, default_subreddit):
    """Search returns results for a known term."""
    when = given.search('python', subreddit=default_subreddit, limit=5)
    assert_that(when, instance_of(dict))
    assert_that(when.get('data'), not_none())


@pytest.mark.sanity
def test_get_comments(given, default_subreddit):
    """Fetches comments for the first hot post."""
    posts = given.get_posts(default_subreddit, sort='hot', limit=1)
    children = posts.get('data', {}).get('children', [])
    if not children:
        pytest.skip("No posts found in subreddit")
    article_id = children[0]['data']['id']
    when = ApiServiceRedditSubreddits(CONFIG).get_comments(default_subreddit, article_id, limit=10)
    assert_that(when, instance_of(list))
    assert_that(len(when), greater_than_or_equal_to(1))
