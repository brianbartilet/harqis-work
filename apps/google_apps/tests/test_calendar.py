import pytest
from hamcrest import greater_than

from core.utilities.logging.custom_logger import logger as log

from apps.google_apps.references.web.api.calendar import ApiServiceGoogleCalendar, holidays_aware
from apps.apps_config import CONFIG_MANAGER


@pytest.fixture()
def given():
    given_service = ApiServiceGoogleCalendar(CONFIG_MANAGER.get("GOOGLE_APPS"))
    return given_service


@pytest.mark.smoke
def test_get_holidays(given):
    when = given.get_holidays()
    then = given.verify.common

    then.assert_that(len(when), greater_than(0))

@pytest.mark.smoke
def test_get_holidays_sg(given):
    when = given.get_holidays(country_code='en.singapore')
    then = given.verify.common

    then.assert_that(len(when), greater_than(0))


@holidays_aware(country_code='en.singapore')
def test_holidays_aware():
    log.info("Job Completed From Holidays Check")



