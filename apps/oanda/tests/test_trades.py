import pytest

from core.utilities.data.qlist import QList
from hamcrest import greater_than, equal_to, greater_than_or_equal_to

from apps.oanda.references.web.api.account import ApiServiceOandaAccount
from apps.oanda.references.web.api.open_trades import ApiServiceTrades
from apps.oanda.config import CONFIG


@pytest.mark.smoke
def test_get_open_trades():
    given_service = ApiServiceOandaAccount(CONFIG)
    when_account_info = given_service.get_account_info()

    user_id = QList(when_account_info).first().id

    given_service_trades = ApiServiceTrades(CONFIG)
    when_trades = given_service_trades.get_trades_from_account(user_id)
    then = given_service_trades.verify.common
    then.assert_that(len(when_trades), greater_than_or_equal_to(0))


