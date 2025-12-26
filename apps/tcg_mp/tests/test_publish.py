import pytest
from hamcrest import greater_than, equal_to
from apps.tcg_mp.references.web.api.publish import ApiServiceTcgMpPublish
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




