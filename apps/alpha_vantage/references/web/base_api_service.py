"""
Base service for the Alpha Vantage REST API.

API reference (extensibility):
    https://www.alphavantage.co/documentation/
MCP server (separate, official):
    https://mcp.alphavantage.co/

Alpha Vantage exposes a single endpoint (`https://www.alphavantage.co/query`)
and dispatches behaviour via the `function=...` query string. Authentication
is an `apikey` query parameter attached to every request.

To add a new endpoint, follow the docs URL above:
  1. Identify the `function=` value (e.g. `EARNINGS`, `WTI`, `CPI`).
  2. Pick the matching category service in `references/web/api/`
     (or create a new file for a new category).
  3. Add a method that calls `self._query(function='...', **params)`.
"""
from core.web.services.fixtures.rest import BaseFixtureServiceRest
from core.web.services.core.constants.http_headers import HttpHeaders


class BaseApiServiceAlphaVantage(BaseFixtureServiceRest):
    """
    Shared base for every Alpha Vantage category service.

    Wires the `apikey` query string and JSON content type once. Subclasses
    use `self._query(function, **params)` to dispatch a `function=...` call
    against the single `/query` endpoint.
    """

    def __init__(self, config, **kwargs):
        super(BaseApiServiceAlphaVantage, self).__init__(config=config, **kwargs)
        self.api_key = kwargs.get('api_key', config.app_data['api_key'])
        self.request \
            .add_header(HttpHeaders.CONTENT_TYPE, 'application/json') \
            .add_query_string('apikey', self.api_key) \
            .set_base_uri('query')

    def _query(self, function: str, **params):
        """
        Dispatch a `function=...` call against `/query`.

        Args:
            function: Alpha Vantage function name (e.g. 'GLOBAL_QUOTE').
            **params: Additional query string parameters. None values are
                skipped so optional kwargs can be forwarded blindly.
        """
        self.request.get().add_query_string('function', function)

        for key, value in params.items():
            if value is None:
                continue
            self.request.add_query_string(key, value)

        return self.client.execute_request(self.request.build())
