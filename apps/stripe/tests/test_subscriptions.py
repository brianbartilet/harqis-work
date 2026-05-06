import pytest
from hamcrest import assert_that, instance_of, not_none

from apps.stripe.references.web.api.subscriptions import ApiServiceStripeSubscriptions
from apps.stripe.references.dto.common import DtoStripeListResult
from apps.stripe.config import CONFIG


@pytest.fixture()
def given():
    return ApiServiceStripeSubscriptions(CONFIG)


@pytest.mark.smoke
def test_list_subscriptions(given):
    when = given.list_subscriptions(limit=3, status="all")
    assert_that(when, instance_of(DtoStripeListResult))
    assert_that(when.data, not_none())
