import pytest
from hamcrest import assert_that, not_none, instance_of

from apps.jira.references.web.api.users import ApiServiceJiraUsers
from apps.jira.config import CONFIG


@pytest.fixture()
def given():
    return ApiServiceJiraUsers(CONFIG)


@pytest.mark.smoke
def test_get_myself(given):
    when = given.get_myself()
    assert_that(when, instance_of(dict))
    # Jira DC uses 'name'/'key'; Jira Cloud uses 'accountId'
    assert_that(when.get('name') or when.get('accountId'), not_none())
    assert_that(when.get('displayName'), not_none())


@pytest.mark.sanity
def test_search_users(given):
    me = ApiServiceJiraUsers(CONFIG).get_myself()
    display_name = me.get('displayName', '')
    query = display_name.split()[0] if display_name else 'admin'
    when = given.search_users(query=query, max_results=5)
    assert_that(when, instance_of(list))
