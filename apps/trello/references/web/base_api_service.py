from core.web.services.fixtures.rest import BaseFixtureServiceRest
from core.web.services.core.constants.http_headers import HttpHeaders


class BaseApiServiceTrello(BaseFixtureServiceRest):
    """
    Base service for the Trello REST API.

    Authentication uses API key + token as query parameters on every request:
        https://api.trello.com/1/{resource}?key={key}&token={token}

    Both are read from config.app_data and injected into every request via
    add_query_string so subclasses don't need to repeat them.
    """

    def __init__(self, config, **kwargs):
        super(BaseApiServiceTrello, self).__init__(config=config, **kwargs)
        self.api_key = kwargs.get('api_key', config.app_data['api_key'])
        self.api_token = kwargs.get('api_token', config.app_data['api_token'])

        self.request \
            .add_header(HttpHeaders.CONTENT_TYPE, 'application/json') \
            .add_query_string('key', self.api_key) \
            .add_query_string('token', self.api_token)
