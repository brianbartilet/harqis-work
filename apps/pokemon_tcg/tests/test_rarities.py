import pytest
from hamcrest import assert_that, instance_of

from apps.pokemon_tcg.config import CONFIG
from apps.pokemon_tcg.references.web.api.rarities import ApiServicePokemonTcgRarities


@pytest.fixture()
def given():
    return ApiServicePokemonTcgRarities(CONFIG)


@pytest.mark.smoke
def test_list_rarities(given, call):
    when = call(given.list_rarities)
    assert_that(when, instance_of(list))
    if when:
        # The proxy pipeline's tier-1 rarities must exist verbatim in the API.
        assert 'Illustration Rare' in when
        assert 'Special Illustration Rare' in when
