from __future__ import annotations

from typing import Optional, List, Dict, Any

from apps.google_apps.references.web.base_api_service import BaseApiServiceGoogle
from core.web.services.core.decorators.deserializer import deserialized


class ApiServiceGoogleTranslation(BaseApiServiceGoogle):
    """
    Google Cloud Translation API v2 (Basic).

    Uses API key authentication — no OAuth required.
    Base URL: https://translation.googleapis.com/language/translate/v2

    Free tier: 500,000 characters/month.

    Docs:
      https://cloud.google.com/translate/docs/reference/rest

    Methods:
        translate()          → Translate text to a target language
        detect_language()    → Detect the language of a text
        list_languages()     → List all supported languages
    """

    def __init__(self, config, **kwargs) -> None:
        super().__init__(config, use_gclient=False, **kwargs)
        self._api_key = config.app_data.get('api_key', '')

    @deserialized(dict)
    def translate(self, text: str, target: str,
                  source: str = None,
                  text_format: str = 'text') -> Dict[str, Any]:
        """
        Translate text into the target language.

        Args:
            text:        Text to translate.
            target:      Target language code (BCP-47), e.g. 'es', 'fr', 'ja', 'tl'.
            source:      Source language code. Auto-detected if omitted.
            text_format: 'text' (default) or 'html'.

        Returns:
            Dict with data.translations list. Each item has:
            - translatedText: translated string
            - detectedSourceLanguage: detected language (if source was not provided)
        """
        body: Dict[str, Any] = {
            'q': text,
            'target': target,
            'format': text_format,
        }
        if source:
            body['source'] = source

        self.request.post() \
            .add_query_string('key', self._api_key) \
            .add_json_payload(body)
        return self.client.execute_request(self.request.build())

    @deserialized(dict)
    def detect_language(self, text: str) -> Dict[str, Any]:
        """
        Detect the language of a text string.

        Args:
            text: Text whose language to detect.

        Returns:
            Dict with data.detections list. Each detection has:
            - language: BCP-47 language code
            - confidence: float 0–1
            - isReliable: bool
        """
        self.request.post() \
            .add_uri_parameter('detect') \
            .add_query_string('key', self._api_key) \
            .add_json_payload({'q': text})
        return self.client.execute_request(self.request.build())

    @deserialized(dict)
    def list_languages(self, target: str = 'en') -> Dict[str, Any]:
        """
        List all languages supported by the Translation API.

        Args:
            target: Language code for localizing language names (e.g. 'en' shows names
                    in English, 'es' shows names in Spanish). Default 'en'.

        Returns:
            Dict with data.languages list. Each item has:
            - language: BCP-47 code
            - name: localized language name
        """
        self.request.get() \
            .add_uri_parameter('languages') \
            .add_query_string('key', self._api_key) \
            .add_query_string('target', target)
        return self.client.execute_request(self.request.build())
