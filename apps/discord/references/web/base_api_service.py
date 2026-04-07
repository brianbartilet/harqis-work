from core.web.services.fixtures.rest import BaseFixtureServiceRest
from core.web.services.core.constants.http_headers import HttpHeaders


class BaseApiServiceDiscord(BaseFixtureServiceRest):
    """
    Base service for the Discord REST API v10.

    Base URL:       https://discord.com/api/v10/
    Authentication: Bot token via 'Authorization: Bot <token>' header.
    Token:          Read from config.app_data['bot_token'].

    All IDs (snowflakes) are 64-bit integers returned as strings.
    A valid User-Agent is required to avoid Cloudflare blocks.
    """

    USER_AGENT = "DiscordBot (https://github.com/brianbartilet/harqis-work, 1.0.0)"

    def __init__(self, config, **kwargs):
        super(BaseApiServiceDiscord, self).__init__(config=config, **kwargs)

        bot_token = kwargs.get('bot_token', config.app_data.get('bot_token', ''))

        self.request \
            .add_header(HttpHeaders.CONTENT_TYPE, 'application/json') \
            .add_header(HttpHeaders.AUTHORIZATION, f'Bot {bot_token}') \
            .add_header('User-Agent', self.USER_AGENT)
