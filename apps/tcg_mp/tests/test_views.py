import pytest
from hamcrest import greater_than, equal_to
from apps.tcg_mp.references.web.api.view import ApiServiceTcgMpUserView
from apps.tcg_mp.config import CONFIG


@pytest.fixture()
def given():
    given_service = ApiServiceTcgMpUserView(CONFIG)
    return given_service


@pytest.mark.smoke
def test_get_listings(given):
    when = given.get_listings()
    then = given.verify.common

    then.assert_that(len(when), greater_than(0))






