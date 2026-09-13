from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from hamcrest import assert_that, not_none, instance_of, greater_than

from apps.gemini.references.web.api.generate import ApiServiceGeminiGenerate, DEFAULT_MODEL
from apps.gemini.config import CONFIG
from apps.gemini.tests._helpers import skip_if_gemini_api_error


@pytest.fixture()
def given():
    return ApiServiceGeminiGenerate(CONFIG)


@pytest.mark.parametrize('method, action', [
    ('count_tokens', 'countTokens'),
    ('generate_content', 'generateContent'),
])
@pytest.mark.parametrize('model_kwargs, expected_model', [
    ({}, 'models/gemini-3.6-flash'),
    ({'model': 'models/custom-model'}, 'models/custom-model'),
])
def test_generation_model_request_path(given, monkeypatch, method, action,
                                       model_kwargs, expected_model):
    """Omitted models use the supported default; explicit overrides pass through."""
    add_uri = Mock(wraps=given.request.add_uri_parameter)
    monkeypatch.setattr(given.request, 'add_uri_parameter', add_uri)
    execute = Mock(return_value=SimpleNamespace(data={}))
    monkeypatch.setattr(given.client, 'execute_request', execute)

    getattr(given, method)(prompt='Hello', **model_kwargs)

    add_uri.assert_called_once_with(f'{expected_model}:{action}')
    execute.assert_called_once()


@pytest.mark.skip(reason="API quota depleted - requires billing credits")
@pytest.mark.smoke
def test_generate_content(given):
    when = given.generate_content(prompt='Say hello in one word.')
    assert_that(when, instance_of(dict))
    assert 'candidates' in when, f"Expected 'candidates' key. Actual response: {when}"
    assert_that(len(when['candidates']), greater_than(0))


@pytest.mark.skip(reason="API quota depleted - requires billing credits")
@pytest.mark.smoke
def test_generate_content_with_temperature(given):
    when = given.generate_content(prompt='What is 2 + 2?', temperature=0.0)
    assert_that(when, instance_of(dict))
    assert 'candidates' in when, f"Expected 'candidates' key. Actual response: {when}"


@pytest.mark.skip(reason="API quota depleted - requires billing credits")
@pytest.mark.smoke
def test_generate_content_with_system_instruction(given):
    when = given.generate_content(
        prompt='What is your name?',
        system_instruction='You are a helpful assistant named Gemini.',
    )
    assert_that(when, instance_of(dict))
    assert 'candidates' in when, f"Expected 'candidates' key. Actual response: {when}"


@pytest.mark.smoke
def test_count_tokens(given):
    when = given.count_tokens(prompt='Hello, how are you today?')
    skip_if_gemini_api_error(when)
    assert_that(when, instance_of(dict))
    assert_that(when.get('totalTokens'), not_none())
    assert_that(when.get('totalTokens'), greater_than(0))
