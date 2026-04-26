from typing import List, Optional

from core.web.services.core.decorators.deserializer import deserialized
from apps.gemini.references.web.base_api_service import BaseApiServiceGemini
from apps.gemini.references.dto.embed import (
    DtoGeminiEmbedContentResponse,
    DtoGeminiBatchEmbedContentsResponse,
)

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

    @deserialized(DtoGeminiEmbedContentResponse)
    def embed_content(
        self,
        text: str,
        model: str = DEFAULT_EMBED_MODEL,
        task_type: Optional[str] = None,
        title: Optional[str] = None,
    ) -> DtoGeminiEmbedContentResponse:
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
            DtoGeminiEmbedContentResponse with embedding.values list.
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

    @deserialized(DtoGeminiBatchEmbedContentsResponse)
    def batch_embed_contents(
        self,
        texts: List[str],
        model: str = DEFAULT_EMBED_MODEL,
        task_type: Optional[str] = None,
    ) -> DtoGeminiBatchEmbedContentsResponse:
        """
        Generate vector embeddings for multiple texts in a single API call.

        Args:
            texts:     List of text strings to embed.
            model:     Model resource name (default 'models/text-embedding-004').
            task_type: Optional task type applied to all requests.

        Returns:
            DtoGeminiBatchEmbedContentsResponse with an embeddings list.
        """
        request_item = {'model': model, 'content': {'parts': [{'text': t}]}}
        if task_type:
            request_item['taskType'] = task_type

        payload = {
            'requests': [
                {**request_item, 'content': {'parts': [{'text': t}]}}
                for t in texts
            ]
        }
        self.request.post() \
            .add_uri_parameter(f'{model}:batchEmbedContents') \
            .add_json_payload(payload)
        return self.client.execute_request(self.request.build())
