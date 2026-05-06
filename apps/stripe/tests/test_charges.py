import pytest
from hamcrest import assert_that, instance_of, not_none

from apps.stripe.references.web.api.charges import ApiServiceStripeCharges
from apps.stripe.references.dto.common import DtoStripeListResult
from apps.stripe.config import CONFIG


@pytest.fixture()
def given():
    return ApiServiceStripeCharges(CONFIG)


@pytest.mark.smoke
def test_list_charges(given):
    when = given.list_charges(limit=3)
    assert_that(when, instance_of(DtoStripeListResult))
    assert_that(when.data, not_none())


@pytest.mark.sanity
def test_get_charge_round_trip(given):
    listing = given.list_charges(limit=1)
    if not listing.data:
        pytest.skip("No charges on this account")
    ch = listing.data[0]
    ch_id = ch.get("id") if isinstance(ch, dict) else ch.id
    when = given.get_charge(ch_id)
    assert_that(when.id, not_none())
