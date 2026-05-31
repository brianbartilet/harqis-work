import pytest
from hamcrest import assert_that, instance_of, is_in

from apps.spotify.references.web.api.player import ApiServiceSpotifyPlayer
from apps.spotify.config import CONFIG


@pytest.fixture()
def given():
    return ApiServiceSpotifyPlayer(CONFIG)


@pytest.mark.smoke
def test_recently_played(given):
    when = given.get_recently_played(limit=10)
    assert_that(when, instance_of(dict))
    assert_that("items", is_in(when))
    assert_that(when["items"], instance_of(list))


@pytest.mark.smoke
def test_currently_playing(given):
    # 204 No Content (nothing playing) surfaces as an empty payload; a
    # playing track surfaces as a dict — both are acceptable.
    when = given.get_currently_playing()
    assert_that(when, instance_of(dict))
