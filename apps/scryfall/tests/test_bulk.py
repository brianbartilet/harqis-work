import gzip
import json

import pytest

from hamcrest import greater_than, equal_to

from apps.scryfall.references.web.api.bulk import (
    ApiServiceScryfallBulkData,
    _bulk_download_uri,
    iter_bulk_cards,
)
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


def test_bulk_download_uri_uses_scryfall_jsonl_contract():
    uri = "https://data.scryfall.io/all-cards/all-cards-20260810211742.jsonl.gz"

    assert _bulk_download_uri({"jsonl_download_uri": uri}) == uri


def test_bulk_download_uri_rejects_malformed_metadata_clearly():
    with pytest.raises(RuntimeError, match="did not include a download URI"):
        _bulk_download_uri([])


def test_iter_bulk_cards_reads_compressed_json_lines(tmp_path):
    bulk_file = tmp_path / "all-cards-20260810211742.jsonl.gz"
    cards = [{"id": "one", "name": "Sol Ring"}, {"id": "two", "name": "Island"}]
    with gzip.open(bulk_file, "wt", encoding="utf-8") as fh:
        for card in cards:
            fh.write(json.dumps(card) + "\n")

    assert list(iter_bulk_cards(bulk_file)) == cards
