"""Grok Models API service — list available xAI models."""
from typing import List

from apps.grok.references.web.base_api_service import BaseApiServiceGrok
from apps.grok.references.dto.chat import DtoGrokModel


class ApiServiceGrokModels(BaseApiServiceGrok):
    """Models service — retrieve the catalogue of available Grok models."""

    def __init__(self, config, **kwargs):
        super().__init__(config, **kwargs)

    def list_models(self) -> List[DtoGrokModel]:
        """Return all models available to the authenticated account."""
        page = self.native_client.models.list()
        models = getattr(page, "data", []) or []
        return [
            DtoGrokModel(
                id=getattr(m, "id", None),
                object=getattr(m, "object", None),
                created=getattr(m, "created", None),
                owned_by=getattr(m, "owned_by", None),
            )
            for m in models
        ]

    def get_model(self, model_id: str) -> DtoGrokModel:
        """Retrieve metadata for a specific model by ID."""
        m = self.native_client.models.retrieve(model_id)
        return DtoGrokModel(
            id=getattr(m, "id", None),
            object=getattr(m, "object", None),
            created=getattr(m, "created", None),
            owned_by=getattr(m, "owned_by", None),
        )
