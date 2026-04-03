from typing import Any

from apps.telegram.references.dto.message import DtoTelegramMessage, DtoTelegramChat, DtoSendMessage
from apps.telegram.references.web.base_api_service import BaseApiServiceTelegram

from core.web.services.core.decorators.deserializer import deserialized


class ApiServiceTelegramMessages(BaseApiServiceTelegram):
    """
    Telegram Bot API — messaging and chat operations.

    Methods:
        send_message()      → Send a text message to a chat
        get_chat()          → Fetch chat/group metadata
        forward_message()   → Forward a message between chats
        get_file()          → Resolve a file_id to a downloadable path
    """

    def __init__(self, config, **kwargs):
        super(ApiServiceTelegramMessages, self).__init__(config, **kwargs)

    @deserialized(dict, child='result')
    def send_message(self, chat_id: Any, text: str, parse_mode: str = None,
                     disable_notification: bool = False, reply_to_message_id: int = None):
        """
        Send a text message to a chat.

        Args:
            chat_id:              Target chat ID (int) or username (str, e.g. '@channel').
            text:                 Message text (up to 4096 characters).
            parse_mode:           'HTML' or 'MarkdownV2' for formatting. None for plain text.
            disable_notification: Send silently without sound (default False).
            reply_to_message_id:  If set, sends as a reply to this message ID.
        """
        payload: dict = {
            'chat_id': chat_id,
            'text': text,
        }
        if parse_mode:
            payload['parse_mode'] = parse_mode
        if disable_notification:
            payload['disable_notification'] = disable_notification
        if reply_to_message_id:
            payload['reply_to_message_id'] = reply_to_message_id

        self.request.post() \
            .add_uri_parameter('sendMessage') \
            .add_json_payload(payload)

        return self.client.execute_request(self.request.build())

    @deserialized(dict, child='result')
    def get_chat(self, chat_id: Any):
        """
        Get up-to-date information about a chat.

        Args:
            chat_id: Chat ID (int) or username (str, e.g. '@channel').
        """
        self.request.get() \
            .add_uri_parameter('getChat') \
            .add_query_string('chat_id', chat_id)

        return self.client.execute_request(self.request.build())

    @deserialized(dict, child='result')
    def forward_message(self, chat_id: Any, from_chat_id: Any, message_id: int,
                        disable_notification: bool = False):
        """
        Forward a message from one chat to another.

        Args:
            chat_id:              Destination chat ID or username.
            from_chat_id:         Source chat ID or username.
            message_id:           Message ID in the source chat.
            disable_notification: Forward silently (default False).
        """
        payload = {
            'chat_id': chat_id,
            'from_chat_id': from_chat_id,
            'message_id': message_id,
            'disable_notification': disable_notification,
        }
        self.request.post() \
            .add_uri_parameter('forwardMessage') \
            .add_json_payload(payload)

        return self.client.execute_request(self.request.build())

    @deserialized(dict, child='result')
    def get_file(self, file_id: str):
        """
        Get basic info about a file and a temporary download link.

        Args:
            file_id: Unique identifier for the file.

        Returns:
            Dict with file_id, file_unique_id, file_size, file_path.
            Download URL: https://api.telegram.org/file/bot{TOKEN}/{file_path}
        """
        self.request.get() \
            .add_uri_parameter('getFile') \
            .add_query_string('file_id', file_id)

        return self.client.execute_request(self.request.build())
