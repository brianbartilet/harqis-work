import pytest
from hamcrest import greater_than_or_equal_to
from apps.tcg_mp.references.web.api.order import ApiServiceTcgMpOrder
from apps.tcg_mp.config import CONFIG


@pytest.fixture()
def given():
    given_service = ApiServiceTcgMpOrder(CONFIG)
    return given_service


@pytest.mark.smoke
def test_auth(given):
    when = given.get_orders()
    then = given.verify.common
    then.assert_that(len(when), greater_than_or_equal_to(0))






