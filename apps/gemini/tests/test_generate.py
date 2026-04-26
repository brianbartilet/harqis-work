import pytest
from hamcrest import assert_that, not_none, instance_of, greater_than

from apps.gemini.references.web.api.generate import ApiServiceGeminiGenerate, DEFAULT_MODEL
from apps.gemini.config import CONFIG


@pytest.fixture()
def given():
    return ApiServiceGeminiGenerate(CONFIG)


@pytest.mark.smoke
def test_generate_content(given):
    when = given.generate_content(prompt='Say hello in one word.')
    assert_that(when, not_none())
    candidates = when.candidates if hasattr(when, 'candidates') else (when.get('candidates') if isinstance(when, dict) else None)
    assert_that(candidates, not_none())
    assert_that(len(candidates), greater_than(0))


@pytest.mark.smoke
def test_generate_content_with_temperature(given):
    when = given.generate_content(prompt='What is 2 + 2?', temperature=0.0)
    assert_that(when, not_none())


@pytest.mark.smoke
def test_generate_content_with_system_instruction(given):
    when = given.generate_content(
        prompt='What is your name?',
        system_instruction='You are a helpful assistant named Gemini.',
    )
    assert_that(when, not_none())


@pytest.mark.smoke
def test_count_tokens(given):
    when = given.count_tokens(prompt='Hello, how are you today?')
    assert_that(when, not_none())
    total = when.total_tokens if hasattr(when, 'total_tokens') else (when.get('total_tokens') if isinstance(when, dict) else None)
    assert_that(total, not_none())
    assert_that(total, greater_than(0))
