import pytest
from hamcrest import assert_that, greater_than
from datetime import timezone

from apps.google_apps.config import CONFIG
from apps.google_apps.references.web.api.calendar import (
    ApiServiceGoogleCalendarEvents,
)

SCOPES_CALENDAR_READONLY = [
    "https://www.googleapis.com/auth/calendar.readonly"
]


@pytest.fixture()
def given_calendar_events():
    return ApiServiceGoogleCalendarEvents(
        CONFIG,
        scopes_list=SCOPES_CALENDAR_READONLY,
        calendar_id="primary",
    )


@pytest.mark.smoke
def test_get_events_today_all_calendars(given_calendar_events):
    when = given_calendar_events.get_all_events_today()

    # using hamcrest directly; or given_calendar_events.verify.common if you want
    assert_that(len(when), greater_than(0))
