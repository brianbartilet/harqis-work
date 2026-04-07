from typing import List, Optional

from apps.discord.references.web.base_api_service import BaseApiServiceDiscord
from core.web.services.core.decorators.deserializer import deserialized


class ApiServiceDiscordMessages(BaseApiServiceDiscord):
    """
    Discord REST API v10 — channel messages and reactions.

    Methods:
        get_messages()          → Fetch messages from a channel
        get_message()           → Fetch a single message
        send_message()          → Post a message to a channel
        send_embed()            → Post an embed message
        reply()                 → Reply to an existing message
        edit_message()          → Edit a posted message
        delete_message()        → Delete a message
        add_reaction()          → React to a message with an emoji
        remove_reaction()       → Remove own reaction
        get_reactions()         → Get users who reacted with an emoji
    """

    def __init__(self, config, **kwargs):
        super(ApiServiceDiscordMessages, self).__init__(config, **kwargs)

    @deserialized(List[dict])
    def get_messages(self, channel_id: str, limit: int = 50,
                     before: str = None, after: str = None, around: str = None):
        """
        Fetch messages from a channel.

        Args:
            channel_id: Target channel snowflake ID.
            limit:      Number of messages to return (1–100). Default 50.
            before:     Return messages before this message ID.
            after:      Return messages after this message ID.
            around:     Return messages around this message ID.
        """
        self.request.get() \
            .add_uri_parameter('channels') \
            .add_uri_parameter(channel_id) \
            .add_uri_parameter('messages') \
            .add_query_string('limit', limit)
        if before:
            self.request.add_query_string('before', before)
        if after:
            self.request.add_query_string('after', after)
        if around:
            self.request.add_query_string('around', around)
        return self.client.execute_request(self.request.build())

    @deserialized(dict)
    def get_message(self, channel_id: str, message_id: str):
        """
        Fetch a single message by ID.

        Args:
            channel_id: Channel snowflake ID.
            message_id: Message snowflake ID.
        """
        self.request.get() \
            .add_uri_parameter('channels') \
            .add_uri_parameter(channel_id) \
            .add_uri_parameter('messages') \
            .add_uri_parameter(message_id)
        return self.client.execute_request(self.request.build())

    @deserialized(dict)
    def send_message(self, channel_id: str, content: str,
                     tts: bool = False, flags: int = 0):
        """
        Send a plain text message to a channel.

        Args:
            channel_id: Target channel snowflake ID.
            content:    Message text (max 2000 chars).
            tts:        Send as text-to-speech. Default False.
            flags:      Message flags bitfield. Default 0.
        """
        payload = {'content': content, 'tts': tts}
        if flags:
            payload['flags'] = flags
        self.request.post() \
            .add_uri_parameter('channels') \
            .add_uri_parameter(channel_id) \
            .add_uri_parameter('messages') \
            .add_json_payload(payload)
        return self.client.execute_request(self.request.build())

    @deserialized(dict)
    def send_embed(self, channel_id: str, embed: dict, content: str = None):
        """
        Send an embed message to a channel.

        Args:
            channel_id: Target channel snowflake ID.
            embed:      Embed dict — keys: title, description, color, fields, footer, etc.
            content:    Optional plain text above the embed.

        Example embed:
            {
                "title": "Report",
                "description": "Daily summary",
                "color": 0x00ff00,
                "fields": [{"name": "Trades", "value": "5", "inline": True}]
            }
        """
        payload: dict = {'embeds': [embed]}
        if content:
            payload['content'] = content
        self.request.post() \
            .add_uri_parameter('channels') \
            .add_uri_parameter(channel_id) \
            .add_uri_parameter('messages') \
            .add_json_payload(payload)
        return self.client.execute_request(self.request.build())

    @deserialized(dict)
    def reply(self, channel_id: str, message_id: str, content: str,
              mention_author: bool = True):
        """
        Reply to an existing message.

        Args:
            channel_id:     Channel containing the message.
            message_id:     Message to reply to.
            content:        Reply text (max 2000 chars).
            mention_author: Ping the original author. Default True.
        """
        payload = {
            'content': content,
            'message_reference': {
                'type': 0,
                'message_id': message_id,
                'channel_id': channel_id,
                'fail_if_not_exists': False,
            },
            'allowed_mentions': {'replied_user': mention_author},
        }
        self.request.post() \
            .add_uri_parameter('channels') \
            .add_uri_parameter(channel_id) \
            .add_uri_parameter('messages') \
            .add_json_payload(payload)
        return self.client.execute_request(self.request.build())

    @deserialized(dict)
    def edit_message(self, channel_id: str, message_id: str,
                     content: str = None, embeds: list = None):
        """
        Edit a message posted by the bot.

        Args:
            channel_id: Channel containing the message.
            message_id: Message to edit.
            content:    New text content. Pass None to leave unchanged.
            embeds:     New embeds list. Pass None to leave unchanged.
        """
        payload = {}
        if content is not None:
            payload['content'] = content
        if embeds is not None:
            payload['embeds'] = embeds
        self.request.patch() \
            .add_uri_parameter('channels') \
            .add_uri_parameter(channel_id) \
            .add_uri_parameter('messages') \
            .add_uri_parameter(message_id) \
            .add_json_payload(payload)
        return self.client.execute_request(self.request.build())

    def delete_message(self, channel_id: str, message_id: str):
        """
        Delete a message. Requires MANAGE_MESSAGES for others' messages.

        Args:
            channel_id: Channel containing the message.
            message_id: Message to delete.
        """
        self.request.delete() \
            .add_uri_parameter('channels') \
            .add_uri_parameter(channel_id) \
            .add_uri_parameter('messages') \
            .add_uri_parameter(message_id)
        return self.client.execute_request(self.request.build())

    def add_reaction(self, channel_id: str, message_id: str, emoji: str):
        """
        Add a reaction to a message.

        Args:
            channel_id: Channel containing the message.
            message_id: Message to react to.
            emoji:      Unicode emoji (e.g. '👍') or custom emoji 'name:id'.
        """
        import urllib.parse
        encoded = urllib.parse.quote(emoji)
        self.request.put() \
            .add_uri_parameter('channels') \
            .add_uri_parameter(channel_id) \
            .add_uri_parameter('messages') \
            .add_uri_parameter(message_id) \
            .add_uri_parameter('reactions') \
            .add_uri_parameter(encoded) \
            .add_uri_parameter('@me')
        return self.client.execute_request(self.request.build())

    def remove_reaction(self, channel_id: str, message_id: str, emoji: str):
        """
        Remove the bot's reaction from a message.

        Args:
            channel_id: Channel containing the message.
            message_id: Message ID.
            emoji:      Emoji to remove.
        """
        import urllib.parse
        encoded = urllib.parse.quote(emoji)
        self.request.delete() \
            .add_uri_parameter('channels') \
            .add_uri_parameter(channel_id) \
            .add_uri_parameter('messages') \
            .add_uri_parameter(message_id) \
            .add_uri_parameter('reactions') \
            .add_uri_parameter(encoded) \
            .add_uri_parameter('@me')
        return self.client.execute_request(self.request.build())

    @deserialized(List[dict])
    def get_reactions(self, channel_id: str, message_id: str, emoji: str,
                      limit: int = 25):
        """
        Get users who reacted with a specific emoji.

        Args:
            channel_id: Channel containing the message.
            message_id: Message ID.
            emoji:      Emoji (unicode or 'name:id').
            limit:      Max users to return (1–100). Default 25.

        Returns:
            List of User objects.
        """
        import urllib.parse
        encoded = urllib.parse.quote(emoji)
        self.request.get() \
            .add_uri_parameter('channels') \
            .add_uri_parameter(channel_id) \
            .add_uri_parameter('messages') \
            .add_uri_parameter(message_id) \
            .add_uri_parameter('reactions') \
            .add_uri_parameter(encoded) \
            .add_query_string('limit', limit)
        return self.client.execute_request(self.request.build())
