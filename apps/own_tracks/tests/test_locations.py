import pytest
from hamcrest import assert_that, instance_of, greater_than_or_equal_to, not_none

from apps.own_tracks.references.web.api.locations import (
    ApiServiceOwnTracksLocations,
    _to_recorder_time,
)
from apps.own_tracks.config import CONFIG


@pytest.fixture()
def given():
    return ApiServiceOwnTracksLocations(CONFIG)


@pytest.mark.smoke
def test_list_devices(given):
    """Recorder is reachable and returns device registry."""
    when = given.list_devices()
    assert_that(when, instance_of(dict))


@pytest.mark.smoke
def test_get_last_all_devices(given):
    """Returns last known location for all tracked devices."""
    when = given.get_last()
    assert_that(when, instance_of(list))
    assert_that(len(when), greater_than_or_equal_to(0))


@pytest.mark.sanity
def test_get_last_filtered_by_user(given):
    """Filters last location by username from config."""
    user = CONFIG.app_data.get('default_user')
    if not user:
        pytest.skip("No default_user configured in app_data")
    when = given.get_last(user=user)
    assert_that(when, instance_of(list))


@pytest.mark.sanity
def test_get_history(given):
    """Returns location history for default user/device."""
    user = CONFIG.app_data.get('default_user')
    device = CONFIG.app_data.get('default_device')
    if not user or not device:
        pytest.skip("No default_user/default_device configured in app_data")
    when = given.get_history(user=user, device=device)
    assert_that(when, instance_of(dict))
    assert_that(when.get('data'), not_none())


def test__to_recorder_time_converts_epoch_to_iso():
    """The Recorder rejects raw Unix epoch for from/to ('impossible date/time
    ranges'); get_history must convert epoch -> UTC ISO. Strings pass through."""
    assert _to_recorder_time(0) == "1970-01-01T00:00:00"
    assert _to_recorder_time(1775490963) == "2026-04-06T15:56:03"
    assert _to_recorder_time("2026-04-06") == "2026-04-06"
    assert _to_recorder_time(None) is None
    assert _to_recorder_time("") is None
