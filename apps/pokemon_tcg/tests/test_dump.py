import pytest
from hamcrest import assert_that, instance_of

from apps.pokemon_tcg.config import CONFIG
from apps.pokemon_tcg.references.data.dump import PokemonTcgDataDump


@pytest.fixture()
def given():
    dump = PokemonTcgDataDump((CONFIG.app_data or {}).get('dump_path'))
    if not dump.is_available():
        pytest.skip("pokemon-tcg-data clone not configured (POKEMON_TCG_DATA_DUMP_PATH)")
    return dump


@pytest.mark.smoke
def test_load_sets(given):
    sets = given.load_sets()
    assert_that(sets, instance_of(dict))
    assert sets, "dump clone present but no sets parsed"


@pytest.mark.sanity
def test_find_cards_by_dex_and_rarity(given):
    when = given.find_cards(dex_number=6, rarities=['Special Illustration Rare'])
    assert_that(when, instance_of(list))
    for card in when:
        assert 6 in (card.nationalPokedexNumbers or [])
        assert (card.rarity or '').lower() == 'special illustration rare'
    # Newest-first contract, same as the live API path.
    dates = [c.release_date() for c in when if c.release_date()]
    assert dates == sorted(dates, reverse=True)
