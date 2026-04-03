from typing import List

from apps.telegram.references.dto.message import DtoTelegramUser, DtoTelegramUpdate
from apps.telegram.references.web.base_api_service import BaseApiServiceTelegram

from core.web.services.core.decorators.deserializer import deserialized


class ApiServiceTelegramBot(BaseApiServiceTelegram):
    """
    Telegram Bot API — bot identity and update polling.

    Methods:
        get_me()        → Bot identity (DtoTelegramUser)
        get_updates()   → Pending updates (List[DtoTelegramUpdate])
    """

    def __init__(self, config, **kwargs):
        super(ApiServiceTelegramBot, self).__init__(config, **kwargs)

    @deserialized(DtoTelegramUser, child='result')
    def get_me(self):
        """Return the bot's own identity."""
        self.request.get() \
            .add_uri_parameter('getMe')

        return self.client.execute_request(self.request.build())

    @deserialized(List[dict], child='result')
    def get_updates(self, offset: int = None, limit: int = 100, timeout: int = 0):
        """
        Fetch pending updates via long-polling.

        Args:
            offset: Identifier of the first update to return. Pass (last_update_id + 1)
                    to acknowledge previous updates.
            limit:  Max updates to return (1–100, default 100).
            timeout: Seconds to wait for updates (0 = short-poll).
        """
        params = {'limit': limit, 'timeout': timeout}
        if offset is not None:
            params['offset'] = offset

        self.request.get() \
            .add_uri_parameter('getUpdates') \
            .add_query_string('limit', limit) \
            .add_query_string('timeout', timeout)

        if offset is not None:
            self.request.add_query_string('offset', offset)

        return self.client.execute_request(self.request.build())
