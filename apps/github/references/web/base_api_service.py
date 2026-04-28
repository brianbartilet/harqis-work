import httpx
from core.web.services.fixtures.rest import BaseFixtureServiceRest

_GITHUB_API_BASE = "https://api.github.com"


class BaseApiServiceGitHub(BaseFixtureServiceRest):
    """Base service for the GitHub REST API v3."""

    def __init__(self, config, **kwargs):
        super().__init__(config=config, **kwargs)
        self._token: str = config.app_data["api_token"]
        self._headers = {
            "Authorization": f"Bearer {self._token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        }

    def _get(self, path: str, params: dict = None) -> dict | list:
        url = f"{_GITHUB_API_BASE}{path}"
        resp = httpx.get(url, headers=self._headers, params=params or {}, timeout=30)
        resp.raise_for_status()
        return resp.json()

    def _post(self, path: str, body: dict = None) -> dict:
        url = f"{_GITHUB_API_BASE}{path}"
        resp = httpx.post(url, headers=self._headers, json=body or {}, timeout=30)
        resp.raise_for_status()
        return resp.json()

    def _patch(self, path: str, body: dict = None) -> dict:
        url = f"{_GITHUB_API_BASE}{path}"
        resp = httpx.patch(url, headers=self._headers, json=body or {}, timeout=30)
        resp.raise_for_status()
        return resp.json()
