import pytest
from hamcrest import greater_than_or_equal_to
from apps.tcg_mp.references.web.api.cart import ApiServiceTcgMpUserViewCart
from apps.tcg_mp.config import CONFIG


@pytest.fixture()
def given():
    given_service = ApiServiceTcgMpUserViewCart(CONFIG)
    return given_service


@pytest.mark.smoke
def test_get_orders(given):
    when = given.get_account_summary()
    then = given.verify.common
    then.assert_that(when['current_balance'], greater_than_or_equal_to(0))






