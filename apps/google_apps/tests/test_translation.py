import pytest
from hamcrest import assert_that, instance_of, has_key, not_none

from apps.apps_config import CONFIG_MANAGER
from apps.google_apps.references.web.api.translation import ApiServiceGoogleTranslation


def _require_api_key():
    config = CONFIG_MANAGER.get("GOOGLE_TRANSLATION")
    if not config.app_data.get('api_key'):
        pytest.skip("GOOGLE_APPS_API_KEY not configured in .env/apps.env")


@pytest.fixture()
def given():
    _require_api_key()
    return ApiServiceGoogleTranslation(CONFIG_MANAGER.get("GOOGLE_TRANSLATION"))


@pytest.mark.smoke
def test_list_languages(given):
    """Supported languages endpoint is reachable — confirms API key is valid."""
    when = given.list_languages(target='en')
    assert_that(when, instance_of(dict))
    assert_that(when, has_key('data'))
    languages = when.get('data', {}).get('languages', [])
    assert_that(languages, instance_of(list))


@pytest.mark.sanity
def test_translate_english_to_spanish(given):
    """Translates English text to Spanish."""
    when = given.translate('Hello, world!', target='es', source='en')
    assert_that(when, instance_of(dict))
    translations = when.get('data', {}).get('translations', [])
    assert_that(translations, instance_of(list))
    assert_that(translations[0].get('translatedText'), not_none())


@pytest.mark.sanity
def test_translate_with_autodetect(given):
    """Translates text with auto language detection."""
    when = given.translate('Bonjour le monde', target='en')
    assert_that(when, instance_of(dict))
    translations = when.get('data', {}).get('translations', [])
    assert_that(translations[0].get('translatedText'), not_none())


@pytest.mark.sanity
def test_detect_language(given):
    """Detects the language of a text string."""
    when = given.detect_language('こんにちは')
    assert_that(when, instance_of(dict))
    detections = when.get('data', {}).get('detections', [])
    assert_that(detections, instance_of(list))
    assert_that(detections[0][0].get('language'), not_none())
