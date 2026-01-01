import pytest
from hamcrest import equal_to
from apps.ynab.references.web.api.user import ApiServiceYNABUser
from apps.ynab.config import CONFIG


@pytest.fixture()
def given():
    given_service = ApiServiceYNABUser(CONFIG)
    return given_service


@pytest.mark.smoke
def test_get_user_info(given):
    when = given.get_user_info()
    then = given.verify.common
    then.assert_that(len(when['data']['user']['id']), equal_to(36))






