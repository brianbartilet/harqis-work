import pytest
from hamcrest import matches_regexp
from apps.tcg_mp.references.web.base_api_service import BaseApiServiceAppTcgMp
from apps.tcg_mp.config import CONFIG


@pytest.fixture()
def given():
    given_service = BaseApiServiceAppTcgMp(CONFIG)
    return given_service


@pytest.mark.smoke
def test_auth(given):
    when = given.authenticate()
    then = given.verify.common

    jwt_pattern = r'^[A-Za-z0-9\-_]+?\.[A-Za-z0-9\-_]+?\.[A-Za-z0-9\-_]+$'
    then.assert_that(when.data['accessToken'], matches_regexp(jwt_pattern))






