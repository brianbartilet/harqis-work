import pytest
from hamcrest import assert_that, instance_of, not_none

from apps.stripe.references.web.api.events import ApiServiceStripeEvents
from apps.stripe.references.dto.common import DtoStripeListResult
from apps.stripe.config import CONFIG


@pytest.fixture()
def given():
    return ApiServiceStripeEvents(CONFIG)


@pytest.mark.smoke
def test_list_events(given):
    when = given.list_events(limit=3)
    assert_that(when, instance_of(DtoStripeListResult))
    assert_that(when.data, not_none())
