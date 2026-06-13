import pytest
from hamcrest import assert_that, instance_of, not_none

from apps.pokemon_tcg.config import CONFIG
from apps.pokemon_tcg.references.web.api.cards import ApiServicePokemonTcgCards


@pytest.fixture()
def given():
    return ApiServicePokemonTcgCards(CONFIG)


@pytest.mark.smoke
def test_search_cards(given, call):
    when = call(given.search_cards, q='name:charizard', page_size=3)
    assert_that(when, instance_of(list))


@pytest.mark.smoke
def test_search_cards_by_dex_number(given, call):
    # Charizard (#6) — the heavy case the proxy pipeline must handle.
    when = call(given.search_cards_by_dex_number, 6, page_size=10)
    assert_that(when, instance_of(list))
    if when:
        assert_that(when[0].name, not_none())
        assert 6 in (when[0].nationalPokedexNumbers or [])


@pytest.mark.sanity
def test_search_cards_by_dex_number_with_rarity(given, call):
    when = call(given.search_cards_by_dex_number, 6, rarity='Special Illustration Rare', page_size=10)
    assert_that(when, instance_of(list))
    for card in when:
        assert card.rarity == 'Special Illustration Rare'


@pytest.mark.sanity
def test_results_sorted_newest_first(given, call):
    when = call(given.search_cards_by_dex_number, 25, page_size=20)
    assert_that(when, instance_of(list))
    dates = [c.release_date() for c in when if c.release_date()]
    assert dates == sorted(dates, reverse=True)


@pytest.mark.sanity
def test_get_card(given, call):
    when = call(given.get_card, 'sv3pt5-199')  # Charizard ex SIR, '151'
    assert_that(when.id, not_none())
