"""Perplexity Models service.

GET /models — list models available for the Agent API. Identifiers follow
OpenAI naming conventions for third-party tool compatibility.

See: https://docs.perplexity.ai/docs/models
"""
from typing import List

from apps.perplexity.references.web.base_api_service import BaseApiServicePerplexity
from apps.perplexity.references.dto.models import DtoPerplexityModel


class ApiServicePerplexityModels(BaseApiServicePerplexity):
    """Perplexity — list available models."""

    def __init__(self, config, **kwargs):
        super().__init__(config, **kwargs)

    def list_models(self) -> List[DtoPerplexityModel]:
        """Return all models available to the authenticated account."""
        data = self._get("/models")
        items = data.get("data") if isinstance(data, dict) else data
        return [
            DtoPerplexityModel(
                id=m.get("id"),
                object=m.get("object"),
                created=m.get("created"),
                owned_by=m.get("owned_by"),
            )
            for m in (items or [])
        ]
