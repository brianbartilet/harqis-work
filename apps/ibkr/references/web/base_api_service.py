"""
Base service for the Interactive Brokers Flex Web Service.

API reference: https://www.interactivebrokers.com/campus/ibkr-api-page/flex-web-service/
Base URL:      https://ndcdyn.interactivebrokers.com/AccountManagement/FlexWebService/

Authentication is a Flex Web Service token passed as the ``t`` query parameter on
every call (generated in Client Portal → Performance & Reports → Flex Queries).
The token can only download saved Flex Query reports — it cannot place orders.

IBKR rejects requests without a User-Agent header, and paces SendRequest at
1 request/second and 10 requests/minute per token. Responses are XML.
"""
from core.web.services.fixtures.rest import BaseFixtureServiceRest

FLEX_API_VERSION = '3'
USER_AGENT = 'harqis-work/ibkr-flex'


class BaseApiServiceIbkr(BaseFixtureServiceRest):
    """Shared base for every IBKR Flex resource service."""

    def __init__(self, config, **kwargs):
        super(BaseApiServiceIbkr, self).__init__(config=config, **kwargs)
        self.flex_token = kwargs.get('flex_token', config.app_data['flex_token'])
        self.request.add_header('User-Agent', USER_AGENT)

    def flex_get(self, endpoint: str, q: str, **params) -> str:
        """GET a Flex endpoint and return the decoded XML body.

        The request builder resets query strings after every build, so the token
        and version are added per call. Extra ``params`` (e.g. ``fd``/``td``) are
        added when not None.
        """
        self.request.get().add_uri_parameter(endpoint) \
            .add_query_string('t', self.flex_token) \
            .add_query_string('q', q) \
            .add_query_string('v', FLEX_API_VERSION)
        for name, value in params.items():
            if value is not None:
                self.request.add_query_string(name, value)
        response = self.client.execute_request(self.request.build())
        return response.raw_bytes.decode('utf-8')
