from core.web.services.fixtures.rest import BaseFixtureServiceRest
from core.web.services.core.constants.http_headers import HttpHeaders


class BaseApiServicePokemonTcg(BaseFixtureServiceRest):
    """
    Base service for the Pokemon TCG API v2 (https://api.pokemontcg.io/v2/).

    Authentication: an **optional** ``X-Api-Key`` header. Keyless access is
    rate-limited to 30 requests/minute and 1,000/day; a free key from
    https://dev.pokemontcg.io raises that to 20,000/day. The key is read from
    ``config.app_data['api_key']`` and only attached when actually configured,
    so the integration degrades gracefully to keyless limits.

    Docs: https://docs.pokemontcg.io
    """

    #: Pokemon TCG API passes the (optional) key in this custom header.
    API_KEY_HEADER = 'X-Api-Key'

    def __init__(self, config, **kwargs):
        super(BaseApiServicePokemonTcg, self).__init__(config=config, **kwargs)
        api_key = kwargs.get('api_key', (config.app_data or {}).get('api_key'))

        self.request.add_header(HttpHeaders.ACCEPT, 'application/json')
        # Skip blank keys and unresolved ${POKEMON_TCG_API_KEY} placeholders.
        if api_key and not str(api_key).startswith('${'):
            self.request.add_header(self.API_KEY_HEADER, api_key)
