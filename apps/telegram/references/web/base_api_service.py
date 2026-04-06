from core.web.services.fixtures.rest import BaseFixtureServiceRest
from core.web.services.core.constants.http_headers import HttpHeaders


class BaseApiServiceTelegram(BaseFixtureServiceRest):
    """
    Base service for the Telegram Bot API.

    Authentication uses a bot token embedded in the URL path:
        https://api.telegram.org/bot{TOKEN}/METHOD_NAME

    The token is read from config.app_data['bot_token'] and set as the
    base URI prefix so all method calls append naturally underneath it.
    """

    def __init__(self, config, **kwargs):
        super(BaseApiServiceTelegram, self).__init__(config=config, **kwargs)
        self.bot_token = kwargs.get('bot_token', config.app_data['bot_token'])

        # Append the bot token to the client's base_url so that urljoin
        # in __get_raw_url__ doesn't misinterpret 'bot<digits>:<hash>' as a URL scheme.
        self.client.base_url = f"{self.client.base_url}/bot{self.bot_token}"

        self.request.add_header(HttpHeaders.CONTENT_TYPE, 'application/json')
