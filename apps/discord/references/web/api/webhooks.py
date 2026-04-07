from typing import List, Optional

from apps.discord.references.web.base_api_service import BaseApiServiceDiscord
from core.web.services.core.decorators.deserializer import deserialized


class ApiServiceDiscordWebhooks(BaseApiServiceDiscord):
    """
    Discord REST API v10 — webhook management.

    Webhooks allow sending messages to a channel without a full bot connection.
    Incoming webhooks (type 1) have a token embedded in their URL.

    Methods:
        create_webhook()        → Create a webhook in a channel
        get_channel_webhooks()  → List all webhooks in a channel
        get_guild_webhooks()    → List all webhooks in a guild
        execute_webhook()       → Post a message via webhook URL
        edit_webhook_message()  → Edit a message sent via webhook
        delete_webhook()        → Delete a webhook
    """

    def __init__(self, config, **kwargs):
        super(ApiServiceDiscordWebhooks, self).__init__(config, **kwargs)

    @deserialized(dict)
    def create_webhook(self, channel_id: str, name: str):
        """
        Create a webhook in a channel.

        Requires MANAGE_WEBHOOKS permission.
        Name cannot contain 'clyde' or 'discord' (case-insensitive, 1–80 chars).

        Args:
            channel_id: Channel to create the webhook in.
            name:       Webhook display name.
        """
        self.request.post() \
            .add_uri_parameter('channels') \
            .add_uri_parameter(channel_id) \
            .add_uri_parameter('webhooks') \
            .add_json_payload({'name': name})
        return self.client.execute_request(self.request.build())

    @deserialized(List[dict])
    def get_channel_webhooks(self, channel_id: str):
        """List all webhooks in a channel. Requires MANAGE_WEBHOOKS."""
        self.request.get() \
            .add_uri_parameter('channels') \
            .add_uri_parameter(channel_id) \
            .add_uri_parameter('webhooks')
        return self.client.execute_request(self.request.build())

    @deserialized(List[dict])
    def get_guild_webhooks(self, guild_id: str):
        """List all webhooks in a guild. Requires MANAGE_WEBHOOKS."""
        self.request.get() \
            .add_uri_parameter('guilds') \
            .add_uri_parameter(guild_id) \
            .add_uri_parameter('webhooks')
        return self.client.execute_request(self.request.build())

    @deserialized(dict)
    def execute_webhook(self, webhook_id: str, webhook_token: str,
                        content: str = None, username: str = None,
                        avatar_url: str = None, embeds: list = None,
                        wait: bool = True, thread_id: str = None):
        """
        Execute (post to) a webhook.

        At least one of content or embeds must be provided.

        Args:
            webhook_id:    Webhook snowflake ID.
            webhook_token: Webhook token (from webhook URL).
            content:       Message text (max 2000 chars).
            username:      Override the webhook's display name.
            avatar_url:    Override the webhook's avatar URL.
            embeds:        List of embed dicts.
            wait:          Return the created Message object. Default True.
            thread_id:     Post into a thread within the webhook's channel.

        Returns:
            Message object if wait=True, else empty dict.
        """
        payload = {}
        if content:
            payload['content'] = content
        if username:
            payload['username'] = username
        if avatar_url:
            payload['avatar_url'] = avatar_url
        if embeds:
            payload['embeds'] = embeds

        self.request.post() \
            .add_uri_parameter('webhooks') \
            .add_uri_parameter(webhook_id) \
            .add_uri_parameter(webhook_token) \
            .add_query_string('wait', 'true' if wait else 'false') \
            .add_json_payload(payload)

        if thread_id:
            self.request.add_query_string('thread_id', thread_id)

        return self.client.execute_request(self.request.build())

    @deserialized(dict)
    def edit_webhook_message(self, webhook_id: str, webhook_token: str,
                             message_id: str, content: str = None,
                             embeds: list = None):
        """
        Edit a message that was posted via a webhook.

        Args:
            webhook_id:    Webhook snowflake ID.
            webhook_token: Webhook token.
            message_id:    Message to edit (or '@original' for the first message).
            content:       New text. Pass None to leave unchanged.
            embeds:        New embeds. Pass None to leave unchanged.
        """
        payload = {}
        if content is not None:
            payload['content'] = content
        if embeds is not None:
            payload['embeds'] = embeds
        self.request.patch() \
            .add_uri_parameter('webhooks') \
            .add_uri_parameter(webhook_id) \
            .add_uri_parameter(webhook_token) \
            .add_uri_parameter('messages') \
            .add_uri_parameter(message_id) \
            .add_json_payload(payload)
        return self.client.execute_request(self.request.build())

    def delete_webhook(self, webhook_id: str, webhook_token: Optional[str] = None):
        """
        Delete a webhook.

        If webhook_token is provided, no bot auth header is needed.

        Args:
            webhook_id:    Webhook to delete.
            webhook_token: Token for token-based auth (optional).
        """
        self.request.delete().add_uri_parameter('webhooks').add_uri_parameter(webhook_id)
        if webhook_token:
            self.request.add_uri_parameter(webhook_token)
        return self.client.execute_request(self.request.build())
