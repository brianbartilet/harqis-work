import pytest
from hamcrest import assert_that, instance_of, has_key, not_none

from apps.linkedin.references.web.api.profile import ApiServiceLinkedInProfile
from apps.linkedin.config import CONFIG


def _require_token():
    if not CONFIG.app_data.get('access_token'):
        pytest.skip("LINKEDIN_ACCESS_TOKEN not configured in .env/apps.env")


@pytest.fixture()
def given():
    _require_token()
    return ApiServiceLinkedInProfile(CONFIG)


@pytest.mark.smoke
def test_get_me(given):
    """Authenticated member's lite profile is reachable — confirms token is valid."""
    when = given.get_me()
    assert_that(when, instance_of(dict))
    assert_that(when, has_key('sub'))
    assert_that(when.get('sub'), not_none())


@pytest.mark.sanity
def test_get_email(given):
    """Returns the authenticated member's email via OpenID Connect userinfo."""
    when = given.get_email()
    assert_that(when, instance_of(dict))
    assert_that(when, has_key('email'))
    assert_that(when.get('email'), not_none())


@pytest.mark.sanity
def test_get_profile_by_id(given):
    """Fetches a member profile by person ID — requires partner-level access."""
    me = ApiServiceLinkedInProfile(CONFIG).get_me()
    person_id = me.get('sub')
    if not person_id:
        pytest.skip("Could not retrieve person ID from /v2/me")
    when = ApiServiceLinkedInProfile(CONFIG).get_profile(person_id)
    if when.get('status') == 403:
        pytest.skip("get_profile requires LinkedIn Partner Program access — not available for self-serve apps")
    assert_that(when, instance_of(dict))
    assert_that(when, has_key('id'))
