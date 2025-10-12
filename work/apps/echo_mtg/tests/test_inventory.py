import pytest

from hamcrest import greater_than_or_equal_to

from work.apps.echo_mtg.references.web.api.inventory import ApiServiceEchoMTGInventory
from work.apps.echo_mtg.config import CONFIG


@pytest.fixture()
def given_service_account():
    given_service = ApiServiceEchoMTGInventory(CONFIG)
    return given_service


@pytest.mark.smoke
def test_service_account(given_service_account):
    when = given_service_account.get_quick_stats()
    then = given_service_account.verify.common

    then.assert_that(when.acquired_value, greater_than_or_equal_to(0))



