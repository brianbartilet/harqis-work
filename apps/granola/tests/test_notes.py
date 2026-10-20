"""Opt-in live smoke checks; fixture-based transport checks live with ingestion."""
import os
import pytest
from hamcrest import assert_that, instance_of

from apps.granola.config import CONFIG
from apps.granola.references.web.api.notes import ApiServiceGranolaNotes

pytestmark = pytest.mark.skipif(
    os.environ.get("GRANOLA_LIVE_TESTS") != "1",
    reason="Manual opt-in: GRANOLA_LIVE_TESTS=1 and a configured Granola API key",
)


@pytest.mark.smoke
def test_list_notes():
    result = ApiServiceGranolaNotes(CONFIG).list_notes(page_size=1)
    assert_that(result["notes"], instance_of(list))


@pytest.mark.smoke
def test_get_note():
    service = ApiServiceGranolaNotes(CONFIG)
    notes = service.list_notes(page_size=1)["notes"]
    if not notes:
        pytest.skip("No processed notes accessible")
    assert service.get_note(notes[0]["id"]).id == notes[0]["id"]


@pytest.mark.smoke
def test_list_folders():
    assert_that(ApiServiceGranolaNotes(CONFIG).list_folders(page_size=1)["folders"], instance_of(list))
