import pytest
from hamcrest import assert_that, greater_than

from apps.google_apps.config import CONFIG
from apps.google_apps.references.web.api.calendar import  ApiServiceGoogleCalendarEvents


@pytest.fixture()
def given_calendar_events():
    return ApiServiceGoogleCalendarEvents(CONFIG)


@pytest.mark.smoke
def test_get_all_events_today(given_calendar_events):
    when = given_calendar_events.get_all_events_today()

    assert_that(len(when), greater_than(0))
