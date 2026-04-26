from core.web.services.fixtures.rest import BaseFixtureServiceRest
from core.web.services.core.constants.http_headers import HttpHeaders


class BaseApiServiceGemini(BaseFixtureServiceRest):
    """
    Base service for the Google Gemini REST API (v1beta).

    Auth: API key appended as a `key` query parameter on every request,
    registered once on self.request so all subclass methods inherit it.
    """

    def __init__(self, config, **kwargs):
        super(BaseApiServiceGemini, self).__init__(config=config, **kwargs)
        self.request \
            .add_header(HttpHeaders.CONTENT_TYPE, 'application/json') \
            .add_query_string('key', config.app_data['api_key'])
