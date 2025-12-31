import pytest
from hamcrest import equal_to
from apps.tcg_mp.references.web.api.merchant import ApiServiceTcgMpMerchant
from apps.tcg_mp.config import CONFIG


@pytest.fixture()
def given():
    given_service = ApiServiceTcgMpMerchant(CONFIG)
    return given_service


@pytest.mark.smoke
def test_set_listing_status(given):
    when = given.set_listing_status(1)
    then = given.verify.common
    then.assert_that(when['serverStatus'], equal_to(2))





