from core.web.services.fixtures.rest import BaseFixtureServiceRest
from core.web.services.core.constants.http_headers import HttpHeaders

NOTION_API_VERSION = "2022-06-28"


class BaseApiServiceNotion(BaseFixtureServiceRest):
    """
    Base service for the Notion REST API v1.

    Authentication uses an Integration Token (Bearer) on every request.
    The Notion-Version header is required on all requests.

    Both are read from config.app_data and injected into every request
    so subclasses don't need to repeat them.

    Docs: https://developers.notion.com/reference/intro
    """

    def __init__(self, config, **kwargs):
        super(BaseApiServiceNotion, self).__init__(config=config, **kwargs)
        api_token = kwargs.get('api_token', config.app_data['api_token'])

        self.request \
            .add_header(HttpHeaders.CONTENT_TYPE, 'application/json') \
            .add_header(HttpHeaders.AUTHORIZATION, f'Bearer {api_token}') \
            .add_header('Notion-Version', NOTION_API_VERSION)
