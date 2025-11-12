import pytest
from hamcrest import matches_regexp, all_of, has_length

from work.apps.echo_mtg.references.web.api.auth import ApiServiceEchoMTGAuth
from work.apps.echo_mtg.config import CONFIG


@pytest.fixture()
def given_service_account():
    given_service = ApiServiceEchoMTGAuth(CONFIG)
    return given_service


@pytest.mark.smoke
def test_auth(given_service_account):
    when = given_service_account.authenticate()
    then = given_service_account.verify.common

    token = str(when.data['token']).strip()
    then.assert_that(token, all_of(has_length(40), matches_regexp(r"^[0-9a-fA-F]{40}$")))



