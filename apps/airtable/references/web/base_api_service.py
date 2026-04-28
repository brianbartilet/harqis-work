"""Base service for Airtable Web API v0.

Auth: Bearer Personal Access Token (PAT).
Base URL: https://api.airtable.com/v0

Docs: https://airtable.com/developers/web/api/introduction
"""
import httpx
from core.web.services.fixtures.rest import BaseFixtureServiceRest

_AIRTABLE_BASE_URL = "https://api.airtable.com/v0"


class BaseApiServiceAirtable(BaseFixtureServiceRest):
    """Base service for Airtable Web API.

    Provides Bearer-token authenticated httpx helpers for all sub-services.
    """

    def __init__(self, config, **kwargs):
        super().__init__(config=config, **kwargs)
        self._token: str = config.app_data["api_token"]
        self._headers = {
            "Authorization": f"Bearer {self._token}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        }

    def _get(self, path: str, params: dict = None) -> dict:
        url = f"{_AIRTABLE_BASE_URL}{path}"
        resp = httpx.get(url, headers=self._headers, params=params or {}, timeout=30)
        resp.raise_for_status()
        return resp.json()

    def _post(self, path: str, body: dict) -> dict:
        url = f"{_AIRTABLE_BASE_URL}{path}"
        resp = httpx.post(url, headers=self._headers, json=body, timeout=30)
        resp.raise_for_status()
        return resp.json()

    def _patch(self, path: str, body: dict, params: dict = None) -> dict:
        url = f"{_AIRTABLE_BASE_URL}{path}"
        resp = httpx.patch(url, headers=self._headers, json=body, params=params or {}, timeout=30)
        resp.raise_for_status()
        return resp.json()

    def _put(self, path: str, body: dict) -> dict:
        url = f"{_AIRTABLE_BASE_URL}{path}"
        resp = httpx.put(url, headers=self._headers, json=body, timeout=30)
        resp.raise_for_status()
        return resp.json()

    def _delete(self, path: str, params: dict = None) -> dict:
        url = f"{_AIRTABLE_BASE_URL}{path}"
        resp = httpx.delete(url, headers=self._headers, params=params or {}, timeout=30)
        resp.raise_for_status()
        return resp.json()
