import pytest
from hamcrest import greater_than, equal_to, contains_string
from apps.tcg_mp.references.web.api.product import ApiServiceTcgMpProducts
from apps.tcg_mp.config import CONFIG


@pytest.fixture()
def given():
    given_service = ApiServiceTcgMpProducts(CONFIG)
    return given_service


@pytest.mark.smoke
def test_search(given):
    when = given.search_card('Underground River')
    then = given.verify.common

    then.assert_that(len(when), greater_than(0))

@pytest.mark.smoke
def test_product(given):
    when_search = given.search_card('Underground River')
    card_id = when_search[0].id

    when_get_card = given.get_single_card(card_id)
    then = given.verify.common

    then.assert_that(when_get_card.name, contains_string('Underground River'))

@pytest.mark.smoke
def test_product_listed(given):
    when_search = given.search_card('Underground River')
    card_id = when_search[0].id
    # Catalog membership does not imply offers for this printing/finish.
    # Use the envelope-validating reader: API errors and incomplete responses
    # must still fail even when a successful empty result is legitimate.
    response = given.get_pricing_listings(card_id)

    assert isinstance(response, list)
    assert all(isinstance(row, dict) for row in response)



