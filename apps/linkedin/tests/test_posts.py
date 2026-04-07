import pytest
from hamcrest import assert_that, instance_of, has_key

from apps.linkedin.references.web.api.posts import ApiServiceLinkedInPosts
from apps.linkedin.config import CONFIG


def _require_token():
    if not CONFIG.app_data.get('access_token'):
        pytest.skip("LINKEDIN_ACCESS_TOKEN not configured in .env/apps.env")
    if not CONFIG.app_data.get('person_id'):
        pytest.skip("LINKEDIN_PERSON_ID not configured in .env/apps.env")


@pytest.fixture()
def given():
    _require_token()
    return ApiServiceLinkedInPosts(CONFIG)


@pytest.mark.sanity
def test_get_post(given):
    """Fetches a known post by URN — confirms token has read access."""
    post_urn = CONFIG.app_data.get('default_post_urn')
    if not post_urn:
        pytest.skip("LINKEDIN_DEFAULT_POST_URN not configured in .env/apps.env")
    when = given.get_post(post_urn)
    if when.get('status') == 403:
        pytest.skip("get_post requires LinkedIn Partner Program access — not available for self-serve apps")
    assert_that(when, instance_of(dict))
    assert_that(when, has_key('author'))
