from core.web.services.fixtures.rest import BaseFixtureServiceRest
from core.web.services.core.constants.http_headers import HttpHeaders


class BaseApiServiceLooki(BaseFixtureServiceRest):
    """Shared read-only client for ``https://open.looki.tech/api/v1``.

    The developer API uses ``X-API-Key`` rather than Bearer authentication.
    Access is approval-controlled at https://web.looki.tech/api-keys.
    """

    API_KEY_HEADER = "X-API-Key"

    def __init__(self, config, **kwargs):
        super().__init__(config=config, **kwargs)
        api_key = kwargs.get("api_key", (config.app_data or {}).get("api_key", ""))
        self.request \
            .add_header(self.API_KEY_HEADER, api_key) \
            .add_header(HttpHeaders.CONTENT_TYPE, "application/json") \
            .add_header(HttpHeaders.ACCEPT, "application/json")
