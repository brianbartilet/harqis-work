from typing import List

from core.web.services.core.decorators.deserializer import deserialized
from apps.gemini.references.web.base_api_service import BaseApiServiceGemini
from apps.gemini.references.dto.models import DtoGeminiModel


class ApiServiceGeminiModels(BaseApiServiceGemini):
    """
    Google Gemini API — model discovery.

    Methods:
        list_models()  → All models available to the authenticated API key
        get_model()    → Single model by resource name
    """

    def __init__(self, config, **kwargs):
        super(ApiServiceGeminiModels, self).__init__(config, **kwargs)

    @deserialized(dict)
    def list_models(self, page_size: int = 50, page_token: str = None) -> dict:
        """
        List all Gemini models available to the configured API key.

        Args:
            page_size:  Maximum number of models to return (default 50).
            page_token: Pagination token from a previous response.

        Returns:
            Dict with keys: models (list), nextPageToken.
        """
        self.request.get().add_uri_parameter('models')
        self.request.add_query_string('pageSize', page_size)
        if page_token:
            self.request.add_query_string('pageToken', page_token)
        return self.client.execute_request(self.request.build())

    @deserialized(DtoGeminiModel)
    def get_model(self, model_name: str) -> DtoGeminiModel:
        """
        Get metadata for a specific Gemini model.

        Args:
            model_name: Full resource name, e.g. 'models/gemini-2.0-flash'.

        Returns:
            DtoGeminiModel with token limits and supported methods.
        """
        self.request.get().add_uri_parameter(model_name)
        return self.client.execute_request(self.request.build())
