import gzip
import json

from workflows.purchases.helpers.helper import load_scryfall_bulk_data


def test_load_scryfall_bulk_data_indexes_latest_compressed_jsonl(tmp_path):
    older = tmp_path / "all-cards-20260809211742.jsonl.gz"
    newer = tmp_path / "all-cards-20260810211742.jsonl.gz"

    with gzip.open(older, "wt", encoding="utf-8") as fh:
        fh.write(json.dumps({"id": "old", "name": "Old card"}) + "\n")
    with gzip.open(newer, "wt", encoding="utf-8") as fh:
        fh.write(json.dumps({"id": "new", "name": "New card"}) + "\n")

    assert load_scryfall_bulk_data(str(tmp_path)) == {
        "new": {"id": "new", "name": "New card"},
    }