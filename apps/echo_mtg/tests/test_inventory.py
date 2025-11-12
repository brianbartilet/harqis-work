import pytest

from hamcrest import greater_than_or_equal_to

from apps.echo_mtg.references.web.api.inventory import ApiServiceEchoMTGInventory
from apps.echo_mtg.references.web.api.auth import ApiServiceEchoMTGAuth

from apps.echo_mtg.config import CONFIG


@pytest.fixture()
def given_account():
    auth = ApiServiceEchoMTGAuth(CONFIG)
    response = auth.authenticate()
    given_service = ApiServiceEchoMTGInventory(CONFIG, token=response.data['token'])
    return given_service


@pytest.mark.smoke
def test_service_account(given_account):
    when = given_account.get_quick_stats()
    then = given_account.verify.common

    then.assert_that(when.acquired_value, greater_than_or_equal_to(0))



