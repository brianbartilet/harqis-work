from core.web.services.fixtures.rest import BaseFixtureServiceRest
from core.web.services.core.constants.http_headers import HttpHeaders


class BaseApiServiceLinkedIn(BaseFixtureServiceRest):
    """
    Base service for LinkedIn REST API v2.

    Authentication uses a long-lived OAuth2 access token (valid 60 days)
    stored in app_data.access_token. The token is obtained via the
    authorization code flow and must be refreshed manually when it expires.

    All requests include:
        Authorization: Bearer {access_token}
        X-Restli-Protocol-Version: 2.0.0
        Content-Type: application/json
    """

    def __init__(self, config, **kwargs):
        super(BaseApiServiceLinkedIn, self).__init__(config=config, **kwargs)
        access_token = kwargs.get('access_token', config.app_data.get('access_token', ''))
        self.request \
            .add_header(HttpHeaders.CONTENT_TYPE, 'application/json') \
            .add_header(HttpHeaders.AUTHORIZATION, f'Bearer {access_token}') \
            .add_header('X-Restli-Protocol-Version', '2.0.0')
