import pytest
from hamcrest import assert_that, not_none, instance_of, greater_than

from apps.perplexity.references.web.api.chat import ApiServicePerplexityChat
from apps.perplexity.references.web.api.search import ApiServicePerplexitySearch
from apps.perplexity.references.web.api.embeddings import ApiServicePerplexityEmbeddings
from apps.perplexity.references.web.api.models import ApiServicePerplexityModels
from apps.perplexity.references.dto.chat import DtoPerplexityChatResponse
from apps.perplexity.references.dto.search import DtoPerplexitySearchResponse
from apps.perplexity.references.dto.embeddings import DtoPerplexityEmbeddingResponse
from apps.perplexity.references.dto.models import DtoPerplexityModel
from apps.perplexity.config import CONFIG


_SKIP_REASON = "Perplexity API key not yet provisioned — set PERPLEXITY_API_KEY in .env/apps.env to enable"


@pytest.fixture()
def chat():
    return ApiServicePerplexityChat(CONFIG)


@pytest.fixture()
def search_svc():
    return ApiServicePerplexitySearch(CONFIG)


@pytest.fixture()
def embeddings_svc():
    return ApiServicePerplexityEmbeddings(CONFIG)


@pytest.fixture()
def models_svc():
    return ApiServicePerplexityModels(CONFIG)


@pytest.mark.smoke
@pytest.mark.skip(reason=_SKIP_REASON)
def test_chat_complete(chat):
    result = chat.complete(prompt="Say 'hello' in one word.", max_tokens=10)
    assert_that(result, instance_of(DtoPerplexityChatResponse))
    assert_that(result.id, not_none())
    assert_that(result.output_text, not_none())


@pytest.mark.smoke
@pytest.mark.skip(reason=_SKIP_REASON)
def test_chat_with_search_filters(chat):
    result = chat.complete(
        prompt="What happened in tech news today?",
        search_recency_filter="day",
        max_tokens=200,
    )
    assert_that(result, instance_of(DtoPerplexityChatResponse))
    assert_that(result.output_text, not_none())


@pytest.mark.smoke
@pytest.mark.skip(reason=_SKIP_REASON)
def test_list_models(models_svc):
    result = models_svc.list_models()
    assert_that(result, instance_of(list))
    assert_that(len(result), greater_than(0))
    assert_that(result[0], instance_of(DtoPerplexityModel))
    assert_that(result[0].id, not_none())


@pytest.mark.sanity
@pytest.mark.skip(reason=_SKIP_REASON)
def test_search(search_svc):
    result = search_svc.search(query="Perplexity AI", max_results=5)
    assert_that(result, instance_of(DtoPerplexitySearchResponse))
    assert_that(result.results, not_none())
    assert_that(len(result.results), greater_than(0))


@pytest.mark.sanity
@pytest.mark.skip(reason=_SKIP_REASON)
def test_embed(embeddings_svc):
    result = embeddings_svc.embed(input="hello world")
    assert_that(result, instance_of(DtoPerplexityEmbeddingResponse))
    assert_that(result.data, not_none())
    assert_that(len(result.data), greater_than(0))
    assert_that(result.data[0].embedding, not_none())


@pytest.mark.sanity
@pytest.mark.skip(reason=_SKIP_REASON)
def test_async_chat_submit_and_get(chat):
    submission = chat.submit_async(
        messages=[{"role": "user", "content": "Summarise the latest AI safety research."}],
        model="sonar-deep-research",
    )
    assert_that(submission, instance_of(dict))
    assert_that(submission.get("id"), not_none())
