"""Base service for the Stripe REST API v1.

Auth: Bearer token. Stripe documents Basic-Auth-with-secret-key as the
primary mechanism but supports `Authorization: Bearer <secret_key>` as an
explicit alternative for cross-origin / SDK contexts — that's what we use
here so the wire format matches every other Bearer-auth app in the repo.

Content-Type: Stripe is one of the few major APIs that takes
`application/x-www-form-urlencoded` POST bodies, NOT JSON. The framework's
default JSON content-type is overridden to form-urlencoded so create/update
calls go through cleanly. GETs are unaffected.

Docs: https://docs.stripe.com/api
"""
from core.web.services.fixtures.rest import BaseFixtureServiceRest
from core.web.services.core.constants.http_headers import HttpHeaders


class BaseApiServiceStripe(BaseFixtureServiceRest):
    """Base service for the Stripe REST API."""

    def __init__(self, config, **kwargs):
        super().__init__(config=config, **kwargs)
        self.request \
            .add_header(HttpHeaders.AUTHORIZATION, f'Bearer {config.app_data["api_key"]}') \
            .add_header(HttpHeaders.CONTENT_TYPE, 'application/x-www-form-urlencoded')
