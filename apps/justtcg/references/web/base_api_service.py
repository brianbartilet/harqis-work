from core.web.services.fixtures.rest import BaseFixtureServiceRest
from core.web.services.core.constants.http_headers import HttpHeaders


class BaseApiServiceJusttcg(BaseFixtureServiceRest):
    """
    Base service for the JustTCG REST API (https://api.justtcg.com/v1).

    Authentication: every request must carry the API key in the custom
    ``x-api-key`` header (key format: ``tcg_...``) — JustTCG does **not** use
    an Authorization/Bearer header. The key is read from
    ``config.app_data['api_key']`` and injected here so subclasses never repeat
    it.

    Docs: https://justtcg.com/docs
    """

    #: JustTCG passes the API key in this custom header.
    API_KEY_HEADER = 'x-api-key'

    def __init__(self, config, **kwargs):
        super(BaseApiServiceJusttcg, self).__init__(config=config, **kwargs)
        api_key = kwargs.get('api_key', config.app_data['api_key'])

        self.request \
            .add_header(self.API_KEY_HEADER, api_key) \
            .add_header(HttpHeaders.CONTENT_TYPE, 'application/json') \
            .add_header(HttpHeaders.ACCEPT, 'application/json')
