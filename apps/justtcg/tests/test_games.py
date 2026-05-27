import pytest
from hamcrest import assert_that, instance_of, not_none

from apps.justtcg.references.web.api.games import ApiServiceJusttcgGames
from apps.justtcg.config import CONFIG


@pytest.fixture()
def given():
    return ApiServiceJusttcgGames(CONFIG)


@pytest.mark.smoke
def test_list_games(given, call):
    when = call(given.list_games)
    assert_that(when, instance_of(list))
    if when:
        assert_that(when[0].id, not_none())
        assert_that(when[0].name, not_none())
