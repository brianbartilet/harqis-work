import pytest
from hamcrest import assert_that, instance_of, not_none

from apps.pokemon_tcg.config import CONFIG
from apps.pokemon_tcg.references.web.api.sets import ApiServicePokemonTcgSets


@pytest.fixture()
def given():
    return ApiServicePokemonTcgSets(CONFIG)


@pytest.mark.smoke
def test_list_sets(given, call):
    when = call(given.list_sets, page_size=5, order_by='-releaseDate')
    assert_that(when, instance_of(list))
    if when:
        assert_that(when[0].id, not_none())
        assert_that(when[0].releaseDate, not_none())


@pytest.mark.sanity
def test_get_set(given, call):
    when = call(given.get_set, 'sv3pt5')  # '151'
    assert_that(when.name, not_none())
