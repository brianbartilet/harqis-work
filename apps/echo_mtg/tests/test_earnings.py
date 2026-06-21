import pytest

from apps.echo_mtg.references.web.api.earnings import ApiServiceEchoMTGEarnings
from apps.echo_mtg.config import CONFIG


@pytest.fixture()
def given_account():
    given_service = ApiServiceEchoMTGEarnings(CONFIG)
    return given_service


@pytest.mark.skip(reason="destructive — records a real sale to earnings")
def test_earnings_flow(given_account):
    then = given_account.verify.common

    when_add = given_account.add_sale(emid=92175, acquired_price="1.00", sold_price="4.00", foil=0)
    earnings_id = when_add.data['id'] if hasattr(when_add, 'data') else when_add.get('id')

    when_price = given_account.update_sold_price(earnings_id, 7.33)
    then.assert_that(when_price is not None, True)

    when_date = given_account.update_sold_date(earnings_id, "2026-06-21")
    then.assert_that(when_date is not None, True)
