from core.web.services.fixtures.rest import BaseFixtureServiceRest
from core.web.services.core.constants.http_headers import HttpHeaders


class TelegramApiError(RuntimeError):
    """Raised when Telegram rejects a Bot API request."""


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

    def execute_telegram_request(self):
        """Execute and validate a Telegram Bot API response before deserializing it."""
        response = self.client.execute_request(self.request.build())
        data = getattr(response, 'data', None)
        status_code = int(getattr(response, 'status_code', 0) or 0)

        telegram_error = isinstance(data, dict) and data.get('ok') is False
        http_error = not 200 <= status_code < 300
        if http_error or telegram_error:
            error_code = data.get('error_code') if isinstance(data, dict) else None
            description = data.get('description') if isinstance(data, dict) else None
            code = error_code or status_code or 'unknown'
            detail = description or 'request rejected'
            raise TelegramApiError(f"Telegram Bot API error {code}: {detail}")

        return response
