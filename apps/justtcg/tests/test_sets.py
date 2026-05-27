import pytest
from hamcrest import assert_that, instance_of, not_none

from apps.justtcg.references.web.api.sets import ApiServiceJusttcgSets
from apps.justtcg.config import CONFIG


@pytest.fixture()
def given():
    return ApiServiceJusttcgSets(CONFIG)


@pytest.mark.smoke
def test_list_sets_for_game(given, call):
    # NOTE: the JustTCG /sets endpoint requires a `game` (returns HTTP 400 without one).
    when = call(given.list_sets, game="pokemon", limit=5)
    assert_that(when, instance_of(list))
    if when:
        assert_that(when[0].id, not_none())
        assert_that(when[0].game, not_none())
