import pytest
from hamcrest import assert_that, instance_of, not_none

from apps.justtcg.references.web.api.cards import ApiServiceJusttcgCards
from apps.justtcg.config import CONFIG


@pytest.fixture()
def given():
    return ApiServiceJusttcgCards(CONFIG)


@pytest.mark.smoke
def test_search_cards(given, call):
    when = call(given.search_cards, game="pokemon", limit=5)
    assert_that(when, instance_of(list))


@pytest.mark.sanity
def test_search_cards_biggest_movers(given, call):
    # Sort by 7-day price change — the core pricing-analytics use case.
    when = call(given.search_cards, game="pokemon", order_by="7d", order="desc", limit=5)
    assert_that(when, instance_of(list))
    if when:
        assert_that(when[0].name, not_none())
        assert_that(when[0].variants, not_none())


@pytest.mark.sanity
def test_get_card_returns_variants(given, call, sample_cards):
    when = call(given.get_card, card_id=sample_cards[0].id)
    assert_that(when, instance_of(list))
    if when:
        assert_that(when[0].id, not_none())


@pytest.mark.sanity
def test_batch_cards(given, call, sample_cards):
    items = [{"cardId": c.id} for c in sample_cards if c.id]
    when = call(given.batch_cards, items)
    assert_that(when, instance_of(list))
