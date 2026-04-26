import pytest
from hamcrest import assert_that, not_none, instance_of, greater_than

from apps.gemini.references.web.api.embed import ApiServiceGeminiEmbed, DEFAULT_EMBED_MODEL
from apps.gemini.config import CONFIG


@pytest.fixture()
def given():
    return ApiServiceGeminiEmbed(CONFIG)


@pytest.mark.skip(reason="API quota depleted - requires billing credits")
@pytest.mark.smoke
def test_embed_content(given):
    when = given.embed_content(text='The quick brown fox jumps over the lazy dog.')
    assert_that(when, instance_of(dict))
    assert 'embedding' in when, f"Expected 'embedding' key. Actual response: {when}"
    assert_that(when['embedding'].get('values'), not_none())
    assert_that(len(when['embedding']['values']), greater_than(0))


@pytest.mark.skip(reason="API quota depleted - requires billing credits")
@pytest.mark.smoke
def test_embed_content_with_task_type(given):
    when = given.embed_content(
        text='What is the capital of France?',
        task_type='RETRIEVAL_QUERY',
    )
    assert_that(when, instance_of(dict))
    assert 'embedding' in when, f"Expected 'embedding' key. Actual response: {when}"


@pytest.mark.skip(reason="API quota depleted - requires billing credits")
@pytest.mark.sanity
def test_batch_embed_contents(given):
    texts = ['First document.', 'Second document.', 'Third document.']
    when = given.batch_embed_contents(texts=texts)
    assert_that(when, instance_of(dict))
    assert 'embeddings' in when, f"Expected 'embeddings' key. Actual response: {when}"
    assert_that(len(when['embeddings']), greater_than(0))
