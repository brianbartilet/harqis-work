from typing import List, Optional

from core.web.services.core.decorators.deserializer import deserialized
from apps.gemini.references.web.base_api_service import BaseApiServiceGemini

DEFAULT_EMBED_MODEL = 'models/text-embedding-004'


class ApiServiceGeminiEmbed(BaseApiServiceGemini):
    """
    Google Gemini API — text embeddings.

    Methods:
        embed_content()        → Single text embedding vector
        batch_embed_contents() → Multiple text embeddings in one call
    """

    def __init__(self, config, **kwargs):
        super(ApiServiceGeminiEmbed, self).__init__(config, **kwargs)

    @deserialized(dict)
    def embed_content(
        self,
        text: str,
        model: str = DEFAULT_EMBED_MODEL,
        task_type: Optional[str] = None,
        title: Optional[str] = None,
    ) -> dict:
        """
        Generate a vector embedding for a single piece of text.

        Args:
            text:      The text to embed.
            model:     Model resource name (default 'models/text-embedding-004').
            task_type: Embedding task type — e.g. 'RETRIEVAL_DOCUMENT',
                       'RETRIEVAL_QUERY', 'SEMANTIC_SIMILARITY', 'CLASSIFICATION',
                       'CLUSTERING'. Omit for generic embeddings.
            title:     Optional title for RETRIEVAL_DOCUMENT tasks.

        Returns:
            Raw dict with key: embedding.values (list of floats).
        """
        payload: dict = {
            'model': model,
            'content': {'parts': [{'text': text}]},
        }
        if task_type:
            payload['taskType'] = task_type
        if title:
            payload['title'] = title

        self.request.post() \
            .add_uri_parameter(f'{model}:embedContent') \
            .add_json_payload(payload)
        return self.client.execute_request(self.request.build())

    @deserialized(dict)
    def batch_embed_contents(
        self,
        texts: List[str],
        model: str = DEFAULT_EMBED_MODEL,
        task_type: Optional[str] = None,
    ) -> dict:
        """
        Generate vector embeddings for multiple texts in a single API call.

        Args:
            texts:     List of text strings to embed.
            model:     Model resource name (default 'models/text-embedding-004').
            task_type: Optional task type applied to all requests.

        Returns:
            Raw dict with key: embeddings (list of {values: [float]}).
        """
        def _make_request(t: str) -> dict:
            req = {'model': model, 'content': {'parts': [{'text': t}]}}
            if task_type:
                req['taskType'] = task_type
            return req

        payload = {'requests': [_make_request(t) for t in texts]}
        self.request.post() \
            .add_uri_parameter(f'{model}:batchEmbedContents') \
            .add_json_payload(payload)
        return self.client.execute_request(self.request.build())
