import pytest
from hamcrest import greater_than_or_equal_to, equal_to, matches_regexp
from apps.tcg_mp.references.web.api.order import ApiServiceTcgMpOrder
from apps.tcg_mp.config import CONFIG


@pytest.fixture()
def given():
    given_service = ApiServiceTcgMpOrder(CONFIG)
    return given_service


@pytest.mark.smoke
def test_get_orders(given):
    when = given.get_orders()
    then = given.verify.common
    then.assert_that(len(when), greater_than_or_equal_to(0))

@pytest.mark.smoke
def test_get_order_detail(given):
    when = given.get_orders()
    order_id = when[0].data[0]['order_id']

    when_order = given.get_order_detail(order_id)

    then = given.verify.common
    then.assert_that(when_order['order_id'], equal_to(order_id))

@pytest.mark.smoke
def test_get_order_qr(given):
    when = given.get_orders()
    order_id = when[0].data[0]['order_id']

    when_order = given.get_order_qr_code(order_id)

    image_url_regex = r"^https?://[^\s']+\.(png|jpg|jpeg|gif)$"
    then = given.verify.common
    then.assert_that(when_order['qr'], matches_regexp(image_url_regex))





