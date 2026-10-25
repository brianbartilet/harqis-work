"""Read-only official Granola API transport; never log bodies or credentials."""
import requests

from core.web.services.fixtures.rest import BaseFixtureServiceRest


class GranolaApiError(RuntimeError):
    def __init__(self, status):
        self.status = status
        super().__init__(f"Granola API HTTP {status}")


def configured_api_key(config):
    value = str(config.app_data.get("api_key") or "").strip()
    return value if value and not value.startswith("${") else ""


class BaseApiServiceGranola(BaseFixtureServiceRest):
    def __init__(self, config, **kwargs):
        super().__init__(config=config, **kwargs)
        self._api_key = configured_api_key(config)
        if not self._api_key:
            raise ValueError("GRANOLA_API_KEY is not configured")
        # Credentials must only go to the official origin, never a note URL.
        self.client.base_url = "https://public-api.granola.ai/v1"

    def _get(self, path, **params):
        # Match the HFL app's explicit transport pattern: preserve HTTP status
        # and pagination rather than allowing the framework to swallow errors.
        try:
            with requests.get(
                f"{self.client.base_url}/{path}",
                headers={"Authorization": f"Bearer {self._api_key}"},
                params={k: v for k, v in params.items() if v is not None and v != ""},
                timeout=min(float(self.client.timeout or 30), 60),
                verify=True, allow_redirects=False,
            ) as response:
                if response.status_code != 200:
                    raise GranolaApiError(response.status_code)
                payload = response.json()
        except requests.RequestException:
            raise RuntimeError("Granola transport unavailable") from None
        if not isinstance(payload, dict):
            raise ValueError("Invalid Granola response")
        return payload
