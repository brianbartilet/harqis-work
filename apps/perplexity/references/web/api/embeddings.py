"""Perplexity Embeddings service.

POST /embeddings — generate embedding vectors for one or more input strings.
POST /embeddings/contextualized — document-aware embeddings sharing a context.

See: https://docs.perplexity.ai/docs/embeddings
"""
from typing import Optional, List, Union

from apps.perplexity.references.web.base_api_service import BaseApiServicePerplexity, EMBEDDING_MODEL
from apps.perplexity.references.dto.embeddings import (
    DtoPerplexityEmbeddingResponse,
    DtoPerplexityEmbedding,
    DtoPerplexityEmbeddingUsage,
)


class ApiServicePerplexityEmbeddings(BaseApiServicePerplexity):
    """Perplexity Embeddings — vector encodings for semantic search and similarity."""

    def __init__(self, config, **kwargs):
        super().__init__(config, **kwargs)

    def embed(
        self,
        input: Union[str, List[str]],
        model: Optional[str] = None,
    ) -> DtoPerplexityEmbeddingResponse:
        """Generate an embedding vector for one or more input strings.

        Args:
            input: A single string or list of strings to embed.
            model: Embedding model id (default: sonar-embed).
        """
        body = {
            "model": model or EMBEDDING_MODEL,
            "input": input,
        }
        data = self._post("/embeddings", body)
        return self._map(data)

    def embed_contextualized(
        self,
        inputs: List[str],
        context: str,
        model: Optional[str] = None,
    ) -> DtoPerplexityEmbeddingResponse:
        """Generate document-aware embeddings sharing a common context.

        Args:
            inputs:  List of strings to embed.
            context: Shared context document for all inputs.
            model:   Embedding model id (default: sonar-embed).
        """
        body = {
            "model": model or EMBEDDING_MODEL,
            "input": inputs,
            "context": context,
        }
        data = self._post("/embeddings/contextualized", body)
        return self._map(data)

    def _map(self, data: dict) -> DtoPerplexityEmbeddingResponse:
        items = []
        for d in data.get("data") or []:
            items.append(DtoPerplexityEmbedding(
                object=d.get("object"),
                index=d.get("index"),
                embedding=d.get("embedding"),
            ))
        raw_usage = data.get("usage") or {}
        usage = DtoPerplexityEmbeddingUsage(
            prompt_tokens=raw_usage.get("prompt_tokens"),
            total_tokens=raw_usage.get("total_tokens"),
        ) if raw_usage else None
        return DtoPerplexityEmbeddingResponse(
            object=data.get("object"),
            model=data.get("model"),
            data=items,
            usage=usage,
        )
