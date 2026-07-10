import pytest

from hamcrest import equal_to, greater_than, greater_than_or_equal_to

from apps.scryfall.references.web.api.cards import ApiServiceScryfallCards
from apps.scryfall.config import CONFIG


@pytest.fixture()
def given_account():
    given_service = ApiServiceScryfallCards(CONFIG)
    return given_service


def test_service_account(given_account):
    when = given_account.get_card_metadata('4b4fa784-010d-4b27-9e35-43ad78e1ed5e')
    then = given_account.verify.common

    then.assert_that(when.name, equal_to('Underground River'))
    tcg_id = "{0}_{1}".format(when.set, when.collector_number)
    then.assert_that(tcg_id, equal_to('bro_300'))


@pytest.mark.smoke
def test_get_card_by_name(given_account):
    when = given_account.get_card_by_name('Sol Ring')
    then = given_account.verify.common

    then.assert_that(when['name'], equal_to('Sol Ring'))
    then.assert_that('usd' in when.get('prices', {}), equal_to(True))


@pytest.mark.smoke
def test_get_card_versions(given_account):
    when = given_account.get_card_versions('Sol Ring')
    then = given_account.verify.common

    then.assert_that(len(when), greater_than(1))
    then.assert_that(when[0]['name'], equal_to('Sol Ring'))



