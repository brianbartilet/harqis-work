import pytest

from hamcrest import greater_than

from apps.scryfall.references.web.api.bulk import ApiServiceScryfallBulkData
from apps.scryfall.config import CONFIG


@pytest.fixture()
def given_account():
    given_service = ApiServiceScryfallBulkData(CONFIG)
    return given_service


@pytest.mark.skip(reason="sanity check only")
def test_download(given_account):
    given_account.download_bulk_file()



