import pytest
from hamcrest import assert_that, instance_of, greater_than_or_equal_to, not_none

from apps.own_tracks.references.web.api.locations import ApiServiceOwnTracksLocations
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
