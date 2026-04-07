from typing import List

from apps.discord.references.web.base_api_service import BaseApiServiceDiscord
from core.web.services.core.decorators.deserializer import deserialized


class ApiServiceDiscordGuilds(BaseApiServiceDiscord):
    """
    Discord REST API v10 — guild (server) operations.

    Methods:
        get_guild()         → Guild info and metadata
        get_channels()      → All channels in a guild
        get_member()        → A single guild member
        list_members()      → Paginated list of guild members
        get_roles()         → All roles in a guild
    """

    def __init__(self, config, **kwargs):
        super(ApiServiceDiscordGuilds, self).__init__(config, **kwargs)

    @deserialized(dict)
    def get_guild(self, guild_id: str, with_counts: bool = True):
        """
        Get guild info.

        Args:
            guild_id:    Guild snowflake ID.
            with_counts: Include approximate_member_count and approximate_presence_count.
        """
        self.request.get() \
            .add_uri_parameter('guilds') \
            .add_uri_parameter(guild_id) \
            .add_query_string('with_counts', 'true' if with_counts else 'false')
        return self.client.execute_request(self.request.build())

    @deserialized(List[dict])
    def get_channels(self, guild_id: str):
        """
        Get all channels in a guild (excludes threads).

        Args:
            guild_id: Guild snowflake ID.
        """
        self.request.get() \
            .add_uri_parameter('guilds') \
            .add_uri_parameter(guild_id) \
            .add_uri_parameter('channels')
        return self.client.execute_request(self.request.build())

    @deserialized(dict)
    def get_member(self, guild_id: str, user_id: str):
        """
        Get a single guild member.

        Args:
            guild_id: Guild snowflake ID.
            user_id:  User snowflake ID.
        """
        self.request.get() \
            .add_uri_parameter('guilds') \
            .add_uri_parameter(guild_id) \
            .add_uri_parameter('members') \
            .add_uri_parameter(user_id)
        return self.client.execute_request(self.request.build())

    @deserialized(List[dict])
    def list_members(self, guild_id: str, limit: int = 100, after: str = '0'):
        """
        List guild members (requires GUILD_MEMBERS privileged intent).

        Args:
            guild_id: Guild snowflake ID.
            limit:    Members per page (1–1000). Default 100.
            after:    Snowflake to paginate after. Default '0'.
        """
        self.request.get() \
            .add_uri_parameter('guilds') \
            .add_uri_parameter(guild_id) \
            .add_uri_parameter('members') \
            .add_query_string('limit', limit) \
            .add_query_string('after', after)
        return self.client.execute_request(self.request.build())

    @deserialized(List[dict])
    def get_roles(self, guild_id: str):
        """
        Get all roles in a guild.

        Args:
            guild_id: Guild snowflake ID.
        """
        self.request.get() \
            .add_uri_parameter('guilds') \
            .add_uri_parameter(guild_id) \
            .add_uri_parameter('roles')
        return self.client.execute_request(self.request.build())
