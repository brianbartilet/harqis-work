from typing import List, Optional

from core.web.services.core.decorators.deserializer import deserialized
from apps.gemini.references.web.base_api_service import BaseApiServiceGemini
from apps.gemini.references.dto.models import (
    DtoGeminiGenerateContentResponse,
    DtoGeminiCountTokensResponse,
)

DEFAULT_MODEL = 'models/gemini-2.0-flash'


class ApiServiceGeminiGenerate(BaseApiServiceGemini):
    """
    Google Gemini API — content generation.

    Methods:
        generate_content()  → Generate text from a prompt
        count_tokens()      → Count tokens for a prompt without generating
    """

    def __init__(self, config, **kwargs):
        super(ApiServiceGeminiGenerate, self).__init__(config, **kwargs)

    @deserialized(DtoGeminiGenerateContentResponse)
    def generate_content(
        self,
        prompt: str,
        model: str = DEFAULT_MODEL,
        temperature: Optional[float] = None,
        max_output_tokens: Optional[int] = None,
        top_p: Optional[float] = None,
        top_k: Optional[int] = None,
        system_instruction: Optional[str] = None,
    ) -> DtoGeminiGenerateContentResponse:
        """
        Generate content from a text prompt.

        Args:
            prompt:             The user text prompt.
            model:              Model resource name (default 'models/gemini-2.0-flash').
            temperature:        Sampling temperature 0.0–2.0. Lower = deterministic.
            max_output_tokens:  Maximum tokens in the response.
            top_p:              Nucleus sampling probability mass.
            top_k:              Top-k sampling tokens.
            system_instruction: Optional system-level instruction prepended before the prompt.

        Returns:
            DtoGeminiGenerateContentResponse with candidates and usage metadata.
        """
        payload = {
            'contents': [{'parts': [{'text': prompt}], 'role': 'user'}],
        }
        if system_instruction:
            payload['system_instruction'] = {'parts': [{'text': system_instruction}]}

        generation_config = {}
        if temperature is not None:
            generation_config['temperature'] = temperature
        if max_output_tokens is not None:
            generation_config['maxOutputTokens'] = max_output_tokens
        if top_p is not None:
            generation_config['topP'] = top_p
        if top_k is not None:
            generation_config['topK'] = top_k
        if generation_config:
            payload['generationConfig'] = generation_config

        self.request.post() \
            .add_uri_parameter(f'{model}:generateContent') \
            .add_json_payload(payload)
        return self.client.execute_request(self.request.build())

    @deserialized(DtoGeminiCountTokensResponse)
    def count_tokens(
        self,
        prompt: str,
        model: str = DEFAULT_MODEL,
    ) -> DtoGeminiCountTokensResponse:
        """
        Count the number of tokens a prompt would consume without generating a response.

        Args:
            prompt: The text prompt to tokenize.
            model:  Model resource name (default 'models/gemini-2.0-flash').

        Returns:
            DtoGeminiCountTokensResponse with totalTokens.
        """
        payload = {
            'contents': [{'parts': [{'text': prompt}], 'role': 'user'}],
        }
        self.request.post() \
            .add_uri_parameter(f'{model}:countTokens') \
            .add_json_payload(payload)
        return self.client.execute_request(self.request.build())
