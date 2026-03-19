import pytest

from hamcrest import assert_that, not_none, equal_to, greater_than, instance_of

from core.config.loader import ConfigLoaderService
from core.web.services.core.config.webservice import AppConfigWSClient
from core.config.env_variables import ENV_APP_CONFIG_FILE

from apps.antropic.references.web.base_api_service import BaseApiServiceAnthropic


load_config = ConfigLoaderService(file_name=ENV_APP_CONFIG_FILE).config
CONFIG = AppConfigWSClient(**load_config['ANTHROPIC'])


@pytest.fixture()
def given_service():
    return BaseApiServiceAnthropic(CONFIG)


@pytest.mark.smoke
def test_client_initializes(given_service):
    assert_that(given_service.base_client, not_none())
    assert_that(given_service.async_client, not_none())


@pytest.mark.smoke
def test_client_default_model(given_service):
    assert_that(given_service.model, not_none())


@pytest.mark.sanity
def test_send_message_returns_response(given_service):
    response = given_service.send_message("Say hello.")
    assert_that(response, not_none())
    assert_that(len(response.content), greater_than(0))


@pytest.mark.sanity
def test_send_message_with_system_prompt(given_service):
    response = given_service.send_message(
        prompt="What is 2 + 2?",
        system="You are a calculator. Reply with numeric values only.",
    )
    assert_that(response, not_none())
    assert_that(len(response.content), greater_than(0))


@pytest.mark.sanity
def test_send_message_model_override(given_service):
    response = given_service.send_message(
        prompt="Say hello.",
        model="claude-haiku-4-5-20251001",
        max_tokens=64,
    )
    assert_that(response, not_none())
    assert_that(response.model, not_none())


@pytest.mark.sanity
def test_count_tokens(given_service):
    response = given_service.count_tokens("Hello, how are you?")
    assert_that(response, not_none())
    assert_that(response.input_tokens, greater_than(0))


@pytest.mark.sanity
def test_send_message_async(given_service):
    import asyncio
    response = asyncio.run(given_service.send_message_async("Say hello."))
    assert_that(response, not_none())
    assert_that(len(response.content), greater_than(0))


def test_send_message_raises_without_client():
    service = BaseApiServiceAnthropic.__new__(BaseApiServiceAnthropic)
    service.base_client = None
    service.async_client = None
    with pytest.raises(RuntimeError, match="sync client is not initialized"):
        service.send_message("test")


def test_send_message_async_raises_without_client():
    import asyncio
    service = BaseApiServiceAnthropic.__new__(BaseApiServiceAnthropic)
    service.base_client = None
    service.async_client = None
    with pytest.raises(RuntimeError, match="async client is not initialized"):
        asyncio.run(service.send_message_async("test"))


def test_count_tokens_raises_without_client():
    service = BaseApiServiceAnthropic.__new__(BaseApiServiceAnthropic)
    service.base_client = None
    with pytest.raises(RuntimeError, match="sync client is not initialized"):
        service.count_tokens("test")
