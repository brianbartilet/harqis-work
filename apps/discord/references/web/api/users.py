from typing import List

from apps.discord.references.web.base_api_service import BaseApiServiceDiscord
from core.web.services.core.decorators.deserializer import deserialized


class ApiServiceDiscordUsers(BaseApiServiceDiscord):
    """
    Discord REST API v10 — user and DM operations.

    Methods:
        get_me()            → Current bot/user info
        get_user(id)        → Any user by ID
        get_my_guilds()     → Guilds the bot belongs to
        create_dm(user_id)  → Open a DM channel with a user
    """

    def __init__(self, config, **kwargs):
        super(ApiServiceDiscordUsers, self).__init__(config, **kwargs)

    @deserialized(dict)
    def get_me(self):
        """Get the current bot user object."""
        self.request.get() \
            .add_uri_parameter('users') \
            .add_uri_parameter('@me')
        return self.client.execute_request(self.request.build())

    @deserialized(dict)
    def get_user(self, user_id: str):
        """
        Get a user by their snowflake ID.

        Args:
            user_id: Discord user snowflake ID (string).
        """
        self.request.get() \
            .add_uri_parameter('users') \
            .add_uri_parameter(user_id)
        return self.client.execute_request(self.request.build())

    @deserialized(List[dict])
    def get_my_guilds(self, limit: int = 200, before: str = None, after: str = None):
        """
        Get guilds (servers) the current bot belongs to.

        Args:
            limit:  Max guilds to return (1–200). Default 200.
            before: Return guilds before this snowflake ID.
            after:  Return guilds after this snowflake ID.
        """
        self.request.get() \
            .add_uri_parameter('users') \
            .add_uri_parameter('@me') \
            .add_uri_parameter('guilds') \
            .add_query_string('limit', limit)
        if before:
            self.request.add_query_string('before', before)
        if after:
            self.request.add_query_string('after', after)
        return self.client.execute_request(self.request.build())

    @deserialized(dict)
    def create_dm(self, recipient_id: str):
        """
        Open a DM channel with a user.

        Args:
            recipient_id: Snowflake ID of the user to DM.

        Returns:
            Channel object (type 1 = DM).
        """
        self.request.post() \
            .add_uri_parameter('users') \
            .add_uri_parameter('@me') \
            .add_uri_parameter('channels') \
            .add_json_payload({'recipient_id': recipient_id})
        return self.client.execute_request(self.request.build())
