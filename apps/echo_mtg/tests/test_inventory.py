import pytest

from hamcrest import greater_than_or_equal_to

from apps.echo_mtg.references.web.api.inventory import ApiServiceEchoMTGInventory
from apps.echo_mtg.config import CONFIG


@pytest.fixture()
def given_account():
    given_service = ApiServiceEchoMTGInventory(CONFIG)
    return given_service


@pytest.mark.smoke
def test_service_account(given_account):
    when = given_account.get_quick_stats()
    then = given_account.verify.common

    then.assert_that(when.acquired_value, greater_than_or_equal_to(0))


@pytest.mark.smoke
def test_get_collection(given_account):
    when = given_account.get_collection(tradable_only=1)
    then = given_account.verify.common
    then.assert_that(len(when), greater_than_or_equal_to(0))



