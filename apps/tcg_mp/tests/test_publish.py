import pytest
from hamcrest import greater_than
from apps.tcg_mp.references.web.api.publish import ApiServiceTcgMpPublish
from apps.tcg_mp.references.web.api.view import ApiServiceTcgMpUserView
from apps.tcg_mp.config import CONFIG


@pytest.fixture()
def given():
    given_service = ApiServiceTcgMpPublish(CONFIG)
    return given_service


@pytest.mark.skip(reason="Smoke test only.")
def test_add_listing(given):
    when_add = given.add_listing(price=1, quantity=1, product_id=935158)
    then = given.verify.common

    then.assert_that(len(when_add.data.keys()), greater_than(0))


@pytest.mark.skip(reason="Smoke test only.")
def test_remove_listings(given):
    given_service_view = ApiServiceTcgMpUserView(CONFIG)
    when_listings = given_service_view.get_listings()
    try:
        remove_list = [str(x.listing_id) for x in when_listings]
        given.remove_listings(remove_list)
    except TypeError:
        return



