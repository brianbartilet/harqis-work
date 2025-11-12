import pytest

from hamcrest import greater_than

from work.apps.tcg_mp.references.web.api.filter import ApiServiceTcgMpProducts

from work.apps.tcg_mp.config import CONFIG


@pytest.fixture()
def given():
    given_service = ApiServiceTcgMpProducts(CONFIG)
    return given_service


@pytest.mark.smoke
def test_search(given):
    when = given.search_card('Underground River')
    then = given.verify.common

    then.assert_that(len(when), greater_than(0))



