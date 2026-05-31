import pytest
from hamcrest import assert_that, instance_of, is_in

from apps.spotify.references.web.api.personalization import ApiServiceSpotifyPersonalization
from apps.spotify.config import CONFIG


@pytest.fixture()
def given():
    return ApiServiceSpotifyPersonalization(CONFIG)


@pytest.mark.smoke
def test_top_tracks(given):
    when = given.get_top_tracks(time_range="short_term", limit=10)
    assert_that(when, instance_of(dict))
    assert_that("items", is_in(when))
    assert_that(when["items"], instance_of(list))


@pytest.mark.smoke
def test_top_artists(given):
    when = given.get_top_artists(time_range="short_term", limit=10)
    assert_that(when, instance_of(dict))
    assert_that("items", is_in(when))
    assert_that(when["items"], instance_of(list))
