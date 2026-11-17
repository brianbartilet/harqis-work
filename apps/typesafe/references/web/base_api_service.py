"""Bounded TypeSafe transport; never expose provider errors or credentials."""
import time

import httpx
from core.web.services.fixtures.rest import BaseFixtureServiceRest
from apps.typesafe.references.dto.system_one import TypeSafeError


class BaseApiServiceTypeSafe(BaseFixtureServiceRest):
    def __init__(self, config, *, transport=None, sleep=time.sleep, **kwargs):
        super().__init__(config=config, **kwargs)
        self._key = config.app_data.get('api_key', '')
        if not isinstance(self._key, str) or not self._key.strip() or '${' in self._key:
            raise TypeSafeError('Configure TYPESAFE_API_KEY on the execution host.')
        self.model = config.app_data.get('model', 'jev-latest')
        if not isinstance(self.model, str) or not self.model or len(self.model) > 200:
            raise TypeSafeError('Configure a valid TypeSafe model.')
        self._transport, self._sleep = transport, sleep

    def _send_json(self, method, path, payload=None):
        # Fixed provider origin prevents caller-controlled credential forwarding.
        with httpx.Client(base_url='https://api.typesafe.ai',
                          headers={'Authorization': 'Bearer ' + self._key},
                          timeout=httpx.Timeout(30, connect=5), follow_redirects=False,
                          trust_env=False, transport=self._transport) as client:
            for attempt in range(3):
                try:
                    with client.stream(method, path, json=payload) as response:
                        if response.status_code in {429, 502, 503, 504} and attempt < 2:
                            self._sleep(2 ** attempt)
                            continue
                        if not response.is_success:
                            raise TypeSafeError(f'TypeSafe HTTP {response.status_code}; no decision was made.')
                        content = bytearray()
                        for chunk in response.iter_bytes():
                            content.extend(chunk)
                            if len(content) > 256_000:
                                raise TypeSafeError('TypeSafe response exceeds the size limit.')
                        return httpx.Response(200, content=bytes(content)).json()
                except httpx.HTTPError:
                    # POST admission is ambiguous on timeout; do not retry blindly.
                    raise TypeSafeError('TypeSafe transport failed; inference may have been charged. No decision was made.') from None
                except ValueError:
                    raise TypeSafeError('TypeSafe returned invalid JSON.') from None
