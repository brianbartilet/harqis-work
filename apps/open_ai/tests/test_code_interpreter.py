"""Live integration tests for the OpenAI Code Interpreter service.

Requires OPENAI_API_KEY set in .env/apps.env.
Code Interpreter runs in a sandboxed OpenAI-managed container — no local
Python execution. Tests hit the real API; no mocking.
"""
import pytest
from hamcrest import assert_that, not_none, instance_of, equal_to

from apps.open_ai.config import CONFIG
from apps.open_ai.references.web.api.code_interpreter import ApiServiceOpenAiCodeInterpreter
from apps.open_ai.references.dto.response import DtoOpenAiResponse, DtoOpenAiCodeInterpreterCall


@pytest.fixture()
def given():
    return ApiServiceOpenAiCodeInterpreter(CONFIG)


@pytest.mark.smoke
def test_execute_simple_code(given):
    when = given.execute_code("Calculate 7 * 6 and print the result.")
    assert_that(when, instance_of(DtoOpenAiResponse))
    assert_that(when.id, not_none())
    assert_that(when.status, equal_to("completed"))


@pytest.mark.smoke
def test_output_text_populated(given):
    when = given.execute_code("Print the string 'HARQIS'.")
    assert_that(when.output_text, not_none())


@pytest.mark.smoke
def test_parse_code_calls_returns_list(given):
    result = given.execute_code("Print the first 5 fibonacci numbers.")
    calls = given.parse_code_calls(result)
    assert_that(calls, instance_of(list))


@pytest.mark.sanity
def test_code_call_has_code_field(given):
    result = given.execute_code("Compute the sum of integers 1 through 100 and print it.")
    calls = given.parse_code_calls(result)
    assert len(calls) > 0
    assert_that(calls[0], instance_of(DtoOpenAiCodeInterpreterCall))
    assert_that(calls[0].code, not_none())
    assert_that(calls[0].status, equal_to("completed"))


@pytest.mark.sanity
def test_code_output_contains_logs(given):
    result = given.execute_code("Print the number 5050.")
    calls = given.parse_code_calls(result)
    if calls and calls[0].outputs:
        log_outputs = [o for o in calls[0].outputs if o.type == "logs"]
        assert len(log_outputs) > 0


@pytest.mark.sanity
def test_code_interpreter_continuation(given):
    first = given.execute_code("Set x = 99 and print it.")
    assert_that(first.id, not_none())
    second = given.execute_code(
        "Now multiply x by 2 and print the result.",
        previous_response_id=first.id,
    )
    assert_that(second.id, not_none())
    assert_that(second.status, equal_to("completed"))


@pytest.mark.sanity
def test_usage_tracked(given):
    when = given.execute_code("Print 'done'.")
    assert_that(when.usage, not_none())
    assert when.usage.input_tokens > 0
