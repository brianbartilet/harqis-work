import pytest
from hamcrest import assert_that, not_none, instance_of, greater_than

from apps.grok.references.web.api.chat import ApiServiceGrokChat
from apps.grok.references.web.api.models import ApiServiceGrokModels
from apps.grok.references.web.api.embeddings import ApiServiceGrokEmbeddings
from apps.grok.references.dto.chat import DtoGrokResponse, DtoGrokModel, DtoGrokEmbeddingResponse
from apps.grok.config import CONFIG


@pytest.fixture()
def chat():
    return ApiServiceGrokChat(CONFIG)


@pytest.fixture()
def models_svc():
    return ApiServiceGrokModels(CONFIG)


@pytest.fixture()
def embeddings_svc():
    return ApiServiceGrokEmbeddings(CONFIG)


@pytest.mark.smoke
def test_chat_complete(chat):
    result = chat.complete(prompt="Say 'hello' in one word.", max_tokens=10)
    assert_that(result, instance_of(DtoGrokResponse))
    assert_that(result.id, not_none())
    assert_that(result.output_text, not_none())


@pytest.mark.smoke
def test_list_models(models_svc):
    result = models_svc.list_models()
    assert_that(result, instance_of(list))
    assert_that(len(result), greater_than(0))
    assert_that(result[0], instance_of(DtoGrokModel))
    assert_that(result[0].id, not_none())


@pytest.mark.smoke
@pytest.mark.skip(reason="grok-3-embedding-exp requires separate API access — enable once team access is confirmed")
def test_embed(embeddings_svc):
    result = embeddings_svc.embed(input="hello world")
    assert_that(result, instance_of(DtoGrokEmbeddingResponse))
    assert_that(result.data, not_none())
    assert_that(len(result.data), greater_than(0))
    assert_that(result.data[0].embedding, not_none())


@pytest.mark.sanity
def test_web_search(chat):
    result = chat.web_search(query="What is the current price of Bitcoin?")
    assert_that(result, instance_of(DtoGrokResponse))
    assert_that(result.output_text, not_none())


@pytest.mark.sanity
def test_x_search(chat):
    result = chat.x_search(query="Latest news about xAI Grok")
    assert_that(result, instance_of(DtoGrokResponse))
    assert_that(result.output_text, not_none())
