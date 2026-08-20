import os

import pytest
from hamcrest import assert_that, instance_of

from apps.hfl_corpus.config import CONFIG
from apps.hfl_corpus.references.web.api.entries import ApiServiceHflCorpusEntries


@pytest.fixture()
def given():
    if not os.environ.get("HFL_CORPUS_API_URL", "").strip():
        pytest.skip("HFL_CORPUS_API_URL is not configured for live integration tests")
    return ApiServiceHflCorpusEntries(CONFIG)


@pytest.mark.skip(reason="creates a durable HFL Markdown and Elasticsearch entry")
def test_create_entry(given):
    result = given.create_entry(
        "2026-01-01",
        "12:00",
        "HFL corpus API integration smoke test",
        "Created by an explicitly enabled destructive integration test.",
        tags="#test #hfl-api",
    )
    assert_that(result.delivery, instance_of(str))


@pytest.mark.skip(reason="entry previews may invoke location enrichment services")
def test_preview_entry(given):
    result = given.preview_entry(
        "2026-01-01", "12:00", "Preview", "Preview only", include_location=False
    )
    assert_that(result, instance_of(dict))
