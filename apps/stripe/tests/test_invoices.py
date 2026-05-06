import pytest
from hamcrest import assert_that, instance_of, not_none

from apps.stripe.references.web.api.invoices import ApiServiceStripeInvoices
from apps.stripe.references.dto.common import DtoStripeListResult
from apps.stripe.config import CONFIG


@pytest.fixture()
def given():
    return ApiServiceStripeInvoices(CONFIG)


@pytest.mark.smoke
def test_list_invoices(given):
    when = given.list_invoices(limit=3)
    assert_that(when, instance_of(DtoStripeListResult))
    assert_that(when.data, not_none())
