import pytest
from hamcrest import assert_that, not_none, instance_of, greater_than_or_equal_to

from apps.telegram.references.web.api.bot import ApiServiceTelegramBot
from apps.telegram.config import CONFIG
from apps.telegram.tests._helpers import skip_if_telegram_auth_error


@pytest.fixture()
def given():
    return ApiServiceTelegramBot(CONFIG)


@pytest.mark.smoke
def test_get_me(given):
    when = given.get_me()
    skip_if_telegram_auth_error(when)
    then = given.verify.common
    then.assert_that(when.id, not_none())
    then.assert_that(when.is_bot, not_none())


@pytest.mark.smoke
def test_get_updates(given):
    when = given.get_updates(limit=10)
    skip_if_telegram_auth_error(when)
    assert_that(when, instance_of(list))
