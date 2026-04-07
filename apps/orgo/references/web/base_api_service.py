from core.web.services.fixtures.rest import BaseFixtureServiceRest
from core.web.services.core.constants.http_headers import HttpHeaders


class BaseApiServiceOrgo(BaseFixtureServiceRest):
    """
    Base service for the Orgo AI REST API.

    Base URL:       https://www.orgo.ai/api/
    Authentication: Bearer token via Authorization header.
    API key:        Obtained from https://www.orgo.ai/workspaces

    All concrete services extend this class.
    """

    def __init__(self, config, **kwargs):
        super(BaseApiServiceOrgo, self).__init__(config=config, **kwargs)

        api_key = kwargs.get('api_key', config.app_data.get('api_key', ''))

        self.request \
            .add_header(HttpHeaders.CONTENT_TYPE, 'application/json') \
            .add_header(HttpHeaders.AUTHORIZATION, f'Bearer {api_key}')
