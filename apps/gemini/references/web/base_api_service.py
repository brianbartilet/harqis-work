from core.web.services.fixtures.rest import BaseFixtureServiceRest


class BaseApiServiceGemini(BaseFixtureServiceRest):
    """
    Base service for the Google Gemini REST API (v1beta).

    Auth: API key appended as a `key` query parameter on every request.
    The key is sourced from config.app_data['api_key'] and set as a
    session-level default so all requests inherit it automatically.
    """

    def __init__(self, config, **kwargs):
        super(BaseApiServiceGemini, self).__init__(config=config, **kwargs)
        self.client.session.params = {'key': config.app_data['api_key']}
