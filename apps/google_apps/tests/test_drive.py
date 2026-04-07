import pytest
from hamcrest import assert_that, instance_of, has_key, greater_than_or_equal_to

from apps.apps_config import CONFIG_MANAGER
from apps.google_apps.references.web.api.drive import ApiServiceGoogleDrive


@pytest.fixture()
def given():
    return ApiServiceGoogleDrive(CONFIG_MANAGER.get("GOOGLE_DRIVE"))


@pytest.mark.smoke
def test_list_files(given):
    """Lists files in Drive — confirms OAuth token and scope are valid."""
    when = given.list_files(page_size=10)
    assert_that(when, instance_of(list))


@pytest.mark.sanity
def test_search_files(given):
    """Searches files by name fragment."""
    when = given.search_files(page_size=5)
    assert_that(when, instance_of(list))


@pytest.mark.sanity
def test_list_folders(given):
    """Lists root-level folders."""
    when = given.list_folders()
    assert_that(when, instance_of(list))


@pytest.mark.sanity
def test_get_storage_quota(given):
    """Returns Drive storage quota information."""
    when = given.get_storage_quota()
    assert_that(when, instance_of(dict))
    assert_that(when, has_key('usage'))
