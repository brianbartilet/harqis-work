"""Live integration tests for the OpenAI Responses API service.

Requires OPENAI_API_KEY set in .env/apps.env.
All tests hit the real API — no mocking.
"""
import pytest
from hamcrest import assert_that, not_none, instance_of, equal_to

from apps.open_ai.config import CONFIG
from apps.open_ai.references.web.api.responses import ApiServiceOpenAiResponses
from apps.open_ai.references.dto.response import DtoOpenAiResponse


@pytest.fixture()
def given():
    return ApiServiceOpenAiResponses(CONFIG)


@pytest.mark.smoke
def test_create_simple_response(given):
    when = given.create_response(input="Reply with exactly one word: hello.")
    assert_that(when, instance_of(DtoOpenAiResponse))
    assert_that(when.id, not_none())
    assert_that(when.status, equal_to("completed"))
    assert_that(when.output_text, not_none())


@pytest.mark.smoke
def test_create_response_with_instructions(given):
    when = given.create_response(
        input="What is 2 + 2?",
        instructions="You are a terse math assistant. Reply with only the numeric answer.",
    )
    assert_that(when.id, not_none())
    assert_that(when.output_text, not_none())


@pytest.mark.smoke
def test_usage_is_populated(given):
    when = given.create_response(input="Say hi.")
    assert_that(when.usage, not_none())
    assert when.usage.input_tokens > 0
    assert when.usage.output_tokens > 0


@pytest.mark.sanity
def test_get_stored_response(given):
    created = given.create_response(input="Ping.", store=True)
    assert_that(created.id, not_none())
    retrieved = given.get_response(created.id)
    assert_that(retrieved.id, equal_to(created.id))
    assert_that(retrieved.status, equal_to("completed"))


@pytest.mark.sanity
def test_delete_response(given):
    created = given.create_response(input="Temporary.", store=True)
    result = given.delete_response(created.id)
    assert_that(result.get("deleted"), equal_to(True))
    assert_that(result.get("id"), equal_to(created.id))


@pytest.mark.sanity
def test_multi_turn_conversation(given):
    first = given.create_response(input="Remember: my secret number is 42.", store=True)
    assert_that(first.id, not_none())
    second = given.create_response(
        input="What is my secret number?",
        previous_response_id=first.id,
        store=True,
    )
    assert_that(second.output_text, not_none())
    assert "42" in (second.output_text or "")


@pytest.mark.sanity
def test_output_items_populated(given):
    when = given.create_response(input="Say hello.")
    assert_that(when.output, not_none())
    assert len(when.output) > 0
    assert_that(when.output[0].type, not_none())
