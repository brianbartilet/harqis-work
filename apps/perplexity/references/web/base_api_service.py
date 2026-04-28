"""Base service for Perplexity AI API.

The Perplexity Sonar API is OpenAI-compatible for /chat/completions, so we expose
both an `OpenAI` SDK client (chat completions, streaming, tool use) and raw
httpx helpers for non-OpenAI endpoints (/search, /embeddings, /models).
"""
import httpx
from openai import OpenAI

from core.web.services.fixtures.rest import BaseFixtureServiceRest

DEFAULT_MODEL = "sonar"
EMBEDDING_MODEL = "sonar-embed"
_PERPLEXITY_BASE_URL = "https://api.perplexity.ai"


class BaseApiServicePerplexity(BaseFixtureServiceRest):
    """Base service for Perplexity AI.

    Uses the official openai SDK pointed at https://api.perplexity.ai for chat
    completions (OpenAI-compatible). For Perplexity-specific endpoints
    (/search, /embeddings, /models), use the httpx helpers below.
    """

    def __init__(self, config, **kwargs):
        super().__init__(config=config, **kwargs)
        self._api_key: str = config.app_data["api_key"]
        self.native_client = OpenAI(
            api_key=self._api_key,
            base_url=_PERPLEXITY_BASE_URL,
        )
        self.default_model: str = config.app_data.get("model", DEFAULT_MODEL)

    @property
    def _headers(self) -> dict:
        return {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        }

    def _post(self, path: str, body: dict, timeout: int = 60) -> dict:
        url = f"{_PERPLEXITY_BASE_URL}{path}"
        resp = httpx.post(url, headers=self._headers, json=body, timeout=timeout)
        if not resp.is_success:
            raise RuntimeError(f"Perplexity API {resp.status_code}: {resp.text}")
        return resp.json()

    def _get(self, path: str, params: dict = None, timeout: int = 30) -> dict:
        url = f"{_PERPLEXITY_BASE_URL}{path}"
        resp = httpx.get(url, headers=self._headers, params=params or {}, timeout=timeout)
        if not resp.is_success:
            raise RuntimeError(f"Perplexity API {resp.status_code}: {resp.text}")
        return resp.json()
