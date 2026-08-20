from __future__ import annotations

from pathlib import Path
from typing import Any

import requests

from core.web.services.fixtures.rest import BaseFixtureServiceRest
from core.web.services.core.constants.http_headers import HttpHeaders


class BaseApiServiceHflCorpus(BaseFixtureServiceRest):
    """Bearer-authenticated client for the canonical Activity Corpus API."""

    def __init__(self, config, **kwargs):
        super().__init__(config=config, **kwargs)
        configured_url = kwargs.get("api_url") or config.app_data.get("api_url")
        if not configured_url or str(configured_url).startswith("${"):
            configured_url = config.parameters.get("base_url", "")
        root = str(configured_url).rstrip("/")
        if not root:
            raise ValueError("HFL corpus API URL is not configured")
        self.client.base_url = root if root.endswith("/api/hfl") else f"{root}/api/hfl"

        self.api_token = str(
            kwargs.get("api_key") or config.app_data.get("api_key") or ""
        ).strip()
        if not self.api_token or self.api_token.startswith("${"):
            raise ValueError("HFL corpus API token is not configured")
        self.request \
            .add_header(HttpHeaders.CONTENT_TYPE, "application/json") \
            .add_header(HttpHeaders.AUTHORIZATION, f"Bearer {self.api_token}")

    def _raw_request(self, method: str, path: str, **kwargs) -> requests.Response:
        """Execute a non-JSON or multipart request using the configured transport."""
        headers = dict(kwargs.pop("headers", {}))
        headers.setdefault("Authorization", f"Bearer {self.api_token}")
        timeout = kwargs.pop("timeout", self.client.timeout)
        response = requests.request(
            method,
            f"{self.client.base_url}/{path.lstrip('/')}",
            headers=headers,
            timeout=timeout,
            verify=self.client.verify,
            **kwargs,
        )
        response.raise_for_status()
        return response

    def _download(self, endpoint: str, destination: str | Path) -> dict[str, Any]:
        response = self._raw_request("GET", endpoint)
        target = Path(destination).expanduser().resolve()
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(response.content)
        return {
            "path": str(target),
            "bytes_written": len(response.content),
            "content_type": response.headers.get("content-type", ""),
        }
