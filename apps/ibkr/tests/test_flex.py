import pytest
from hamcrest import assert_that, instance_of, is_not, none, matches_regexp

from apps.ibkr.references.web.api.flex import ApiServiceIbkrFlex
from apps.ibkr.config import CONFIG


@pytest.fixture()
def given_service_flex():
    given_service = ApiServiceIbkrFlex(CONFIG)
    return given_service


@pytest.mark.smoke
def test_send_request_returns_reference(given_service_flex):
    when = given_service_flex.send_request(given_service_flex.default_query_id)
    assert_that(when, matches_regexp(r'^\w+$'))


@pytest.mark.smoke
def test_get_trades(given_service_flex):
    when = given_service_flex.get_trades()
    assert_that(when, instance_of(list))
    for trade in when:
        assert_that(trade.trade_id, is_not(none()))
