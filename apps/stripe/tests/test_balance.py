import pytest
from hamcrest import assert_that, instance_of, not_none

from apps.stripe.references.web.api.balance import ApiServiceStripeBalance
from apps.stripe.references.dto.balance import DtoStripeBalance
from apps.stripe.references.dto.common import DtoStripeListResult
from apps.stripe.config import CONFIG


@pytest.fixture()
def given():
    return ApiServiceStripeBalance(CONFIG)


@pytest.mark.smoke
def test_get_balance(given):
    when = given.get_balance()
    assert_that(when, instance_of(DtoStripeBalance))
    assert_that(when.available, not_none())
    assert_that(when.pending, not_none())


@pytest.mark.smoke
def test_list_balance_transactions(given):
    when = given.list_balance_transactions(limit=3)
    assert_that(when, instance_of(DtoStripeListResult))
    assert_that(when.data, not_none())


@pytest.mark.sanity
def test_get_balance_transaction_round_trip(given):
    listing = given.list_balance_transactions(limit=1)
    if not listing.data:
        pytest.skip("No balance transactions available on this account")
    txn_id = listing.data[0].get("id") if isinstance(listing.data[0], dict) else listing.data[0].id
    when = given.get_balance_transaction(txn_id)
    assert_that(when.id, not_none())
