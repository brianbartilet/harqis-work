import pytest
from hamcrest import assert_that, not_none, instance_of, greater_than_or_equal_to

from apps.notion.references.web.api.users import ApiServiceNotionUsers
from apps.notion.config import CONFIG


@pytest.fixture()
def given():
    return ApiServiceNotionUsers(CONFIG)


@pytest.mark.smoke
def test_get_me(given):
    when = given.get_me()
    assert_that(when, instance_of(dict))
    assert_that(when.get('id'), not_none())
    assert_that(when.get('object'), not_none())


@pytest.mark.sanity
def test_list_users(given):
    when = given.list_users(page_size=10)
    assert_that(when, instance_of(dict))
    assert_that(when.get('results'), instance_of(list))


@pytest.mark.sanity
def test_get_user(given):
    me = given.get_me()
    user_id = me.get('id')
    if not user_id:
        pytest.skip("Could not retrieve bot user ID")
    when = given.get_user(user_id)
    assert_that(when, instance_of(dict))
    assert_that(when.get('id'), not_none())
