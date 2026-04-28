"""Grok Embeddings API service.

Model: grok-3-embedding (4096-dimensional vectors).
See: https://docs.x.ai/api-reference#embeddings
"""
from typing import List, Union

from apps.grok.references.web.base_api_service import BaseApiServiceGrok, EMBEDDING_MODEL
from apps.grok.references.dto.chat import DtoGrokEmbeddingResponse, DtoGrokEmbedding, DtoGrokUsage


class ApiServiceGrokEmbeddings(BaseApiServiceGrok):
    """Embeddings service — convert text into dense vector representations."""

    def __init__(self, config, **kwargs):
        super().__init__(config, **kwargs)

    def embed(
        self,
        input: Union[str, List[str]],
        model: str = EMBEDDING_MODEL,
    ) -> DtoGrokEmbeddingResponse:
        """Generate embeddings for one or more input strings.

        Args:
            input: A string or list of strings to embed.
            model: Embedding model (default: grok-3-embedding, 4096 dims).
        """
        response = self.native_client.embeddings.create(input=input, model=model)
        usage = None
        raw_usage = getattr(response, "usage", None)
        if raw_usage:
            usage = DtoGrokUsage(
                prompt_tokens=getattr(raw_usage, "prompt_tokens", None),
                total_tokens=getattr(raw_usage, "total_tokens", None),
            )
        data = [
            DtoGrokEmbedding(
                object=getattr(e, "object", None),
                embedding=getattr(e, "embedding", None),
                index=getattr(e, "index", None),
            )
            for e in (getattr(response, "data", None) or [])
        ]
        return DtoGrokEmbeddingResponse(
            object=getattr(response, "object", None),
            data=data,
            model=getattr(response, "model", None),
            usage=usage,
        )
