import pytest
from hamcrest import assert_that, greater_than

from apps.apps_config import CONFIG_MANAGER
from apps.google_apps.references.web.api.keep import  ApiServiceGoogleKeepNotes


@pytest.fixture()
def given_calendar_events():
    return ApiServiceGoogleKeepNotes(CONFIG_MANAGER.get("GOOGLE_KEEP"))


@pytest.mark.skip
def test_get_all_notes(given_calendar_events):
    when = given_calendar_events.list_all_notes()

    assert_that(len(when), greater_than(0))
