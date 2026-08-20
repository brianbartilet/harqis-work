import os

import pytest
from hamcrest import assert_that, instance_of

from apps.hfl_corpus.config import CONFIG
from apps.hfl_corpus.references.web.api.documents import ApiServiceHflCorpusDocuments


@pytest.fixture()
def given():
    if not os.environ.get("HFL_CORPUS_API_URL", "").strip():
        pytest.skip("HFL_CORPUS_API_URL is not configured for live integration tests")
    return ApiServiceHflCorpusDocuments(CONFIG)


@pytest.mark.smoke
def test_list_documents(given):
    result = given.list_documents(page_size=1)
    assert_that(result, instance_of(dict))


@pytest.mark.smoke
def test_get_tree(given):
    result = given.get_tree()
    assert_that(result, instance_of(dict))


@pytest.mark.skip(reason="replaces a canonical Markdown document")
def test_update_document(given):
    given.update_document("2026-01-01.md", "# destructive integration test")
