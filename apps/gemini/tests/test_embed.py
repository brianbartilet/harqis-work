import pytest
from hamcrest import assert_that, not_none, instance_of, greater_than

from apps.gemini.references.web.api.embed import ApiServiceGeminiEmbed, DEFAULT_EMBED_MODEL
from apps.gemini.config import CONFIG


@pytest.fixture()
def given():
    return ApiServiceGeminiEmbed(CONFIG)


@pytest.mark.smoke
def test_embed_content(given):
    when = given.embed_content(text='The quick brown fox jumps over the lazy dog.')
    assert_that(when, not_none())
    embedding = when.embedding if hasattr(when, 'embedding') else (when.get('embedding') if isinstance(when, dict) else None)
    assert_that(embedding, not_none())


@pytest.mark.smoke
def test_embed_content_with_task_type(given):
    when = given.embed_content(
        text='What is the capital of France?',
        task_type='RETRIEVAL_QUERY',
    )
    assert_that(when, not_none())


@pytest.mark.sanity
def test_batch_embed_contents(given):
    texts = ['First document.', 'Second document.', 'Third document.']
    when = given.batch_embed_contents(texts=texts)
    assert_that(when, not_none())
    embeddings = when.embeddings if hasattr(when, 'embeddings') else (when.get('embeddings') if isinstance(when, dict) else None)
    assert_that(embeddings, not_none())
    assert_that(len(embeddings), greater_than(0))
