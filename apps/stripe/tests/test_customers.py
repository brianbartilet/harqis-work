import pytest
from hamcrest import assert_that, instance_of, not_none

from apps.stripe.references.web.api.customers import ApiServiceStripeCustomers
from apps.stripe.references.dto.common import DtoStripeListResult
from apps.stripe.config import CONFIG


@pytest.fixture()
def given():
    return ApiServiceStripeCustomers(CONFIG)


@pytest.mark.smoke
def test_list_customers(given):
    when = given.list_customers(limit=3)
    assert_that(when, instance_of(DtoStripeListResult))
    assert_that(when.data, not_none())


@pytest.mark.sanity
def test_get_customer_round_trip(given):
    listing = given.list_customers(limit=1)
    if not listing.data:
        pytest.skip("No customers on this account")
    cust = listing.data[0]
    cust_id = cust.get("id") if isinstance(cust, dict) else cust.id
    when = given.get_customer(cust_id)
    assert_that(when.id, not_none())
