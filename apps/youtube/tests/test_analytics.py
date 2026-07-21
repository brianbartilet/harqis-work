from datetime import date, timedelta

import pytest
from hamcrest import assert_that, instance_of

from apps.youtube.config import CONFIG
from apps.youtube.references.dto.analytics import DtoYouTubeAnalyticsReport
from apps.youtube.references.web.api.analytics import ApiServiceYouTubeAnalytics


@pytest.fixture()
def given():
    return ApiServiceYouTubeAnalytics(CONFIG)


@pytest.mark.smoke
def test_get_channel_summary(given):
    end_date = date.today() - timedelta(days=2)
    start_date = end_date - timedelta(days=7)
    report = given.get_channel_summary(start_date.isoformat(), end_date.isoformat())
    assert_that(report, instance_of(DtoYouTubeAnalyticsReport))
