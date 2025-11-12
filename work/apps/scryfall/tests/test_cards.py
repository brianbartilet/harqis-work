import pytest

from hamcrest import equal_to

from work.apps.scryfall.references.web.api.cards import ApiServiceScryfallCards

from work.apps.scryfall.config import CONFIG


@pytest.fixture()
def given_account():
    given_service = ApiServiceScryfallCards(CONFIG)
    return given_service


@pytest.mark.smoke
def test_service_account(given_account):
    when = given_account.get_card_metadata('4b4fa784-010d-4b27-9e35-43ad78e1ed5e')
    then = given_account.verify.common

    then.assert_that(when.name, equal_to('Underground River'))



