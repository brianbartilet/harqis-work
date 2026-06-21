import pytest
from hamcrest import assert_that, not_none, instance_of, greater_than_or_equal_to

from apps.gemini.references.web.api.models import ApiServiceGeminiModels
from apps.gemini.config import CONFIG
from apps.gemini.tests._helpers import skip_if_gemini_api_error


@pytest.fixture()
def given():
    return ApiServiceGeminiModels(CONFIG)


@pytest.mark.smoke
def test_list_models(given):
    when = given.list_models()
    skip_if_gemini_api_error(when)
    assert_that(when, instance_of(dict))
    assert_that(when.get('models'), not_none())
    assert_that(len(when.get('models', [])), greater_than_or_equal_to(1))


@pytest.mark.smoke
def test_get_model(given):
    when = given.get_model('models/gemini-2.0-flash')
    skip_if_gemini_api_error(when)
    name = when.name if hasattr(when, 'name') else when.get('name') if isinstance(when, dict) else None
    if name is None and hasattr(when, '__dict__') and not any(when.__dict__.values()):
        pytest.skip("Gemini model lookup returned an empty DTO; configured API key/model is unavailable")
    assert_that(when, not_none())
    assert_that(name, not_none())
