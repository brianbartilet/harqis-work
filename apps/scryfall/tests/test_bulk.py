import pytest

from hamcrest import greater_than, equal_to

from apps.scryfall.references.web.api.bulk import ApiServiceScryfallBulkData
from apps.scryfall.config import CONFIG


@pytest.fixture()
def given_account():
    given_service = ApiServiceScryfallBulkData(CONFIG)
    return given_service


@pytest.mark.skip(reason="sanity check only")
def test_download(given_account):
    given_account.download_bulk_file()


@pytest.mark.skip(reason="downloads the multi-hundred-MB bulk file; run manually")
def test_query_bulk(given_account):
    when = given_account.query_bulk('Sol Ring', bulk_data_type='default-cards', field='name', limit=5)
    then = given_account.verify.common

    then.assert_that(len(when), greater_than(0))
    then.assert_that('Sol Ring' in when[0]['name'], equal_to(True))



