import pytest
from hamcrest import assert_that, instance_of, not_none

from apps.stripe.references.web.api.payment_intents import ApiServiceStripePaymentIntents
from apps.stripe.references.dto.common import DtoStripeListResult
from apps.stripe.config import CONFIG


@pytest.fixture()
def given():
    return ApiServiceStripePaymentIntents(CONFIG)


@pytest.mark.smoke
def test_list_payment_intents(given):
    when = given.list_payment_intents(limit=3)
    assert_that(when, instance_of(DtoStripeListResult))
    assert_that(when.data, not_none())
