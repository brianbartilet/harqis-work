import logging
from typing import Any

from mcp.server.fastmcp import FastMCP
from apps.telegram.config import CONFIG
from apps.telegram.references.web.api.bot import ApiServiceTelegramBot
from apps.telegram.references.web.api.messages import ApiServiceTelegramMessages

logger = logging.getLogger("harqis-mcp.telegram")


def register_telegram_tools(mcp: FastMCP):

    @mcp.tool()
    def get_telegram_bot_info() -> dict:
        """Get the identity and details of the configured Telegram bot."""
        logger.info("Tool called: get_telegram_bot_info")
        service = ApiServiceTelegramBot(CONFIG)
        me = service.get_me()
        result = me.__dict__ if hasattr(me, "__dict__") else (me if isinstance(me, dict) else {})
        logger.info("get_telegram_bot_info username=@%s", result.get("username", "?"))
        return result

    @mcp.tool()
    def get_telegram_updates(limit: int = 20) -> list[dict]:
        """Get the latest pending updates (messages) received by the Telegram bot.

        Args:
            limit: Maximum number of updates to return (1–100, default 20).
        """
        logger.info("Tool called: get_telegram_updates limit=%d", limit)
        service = ApiServiceTelegramBot(CONFIG)
        updates = service.get_updates(limit=limit)
        result = updates if isinstance(updates, list) else []
        logger.info("get_telegram_updates returned %d update(s)", len(result))
        return result

    @mcp.tool()
    def send_telegram_message(chat_id: Any, text: str, parse_mode: str = None) -> dict:
        """Send a text message to a Telegram chat or user.

        Args:
            chat_id:    Target chat ID (integer) or public username (e.g. '@mychannel').
                        Use the configured default_chat_id if unsure.
            text:       Message text (up to 4096 characters).
            parse_mode: Optional formatting — 'HTML' or 'MarkdownV2'. Omit for plain text.
        """
        logger.info("Tool called: send_telegram_message chat_id=%s", chat_id)
        service = ApiServiceTelegramMessages(CONFIG)
        result = service.send_message(chat_id=chat_id, text=text, parse_mode=parse_mode)
        result = result if isinstance(result, dict) else {}
        logger.info("send_telegram_message sent message_id=%s", result.get("message_id"))
        return result

    @mcp.tool()
    def send_telegram_message_to_default(text: str, parse_mode: str = None) -> dict:
        """Send a text message to the default configured Telegram chat.

        Uses the default_chat_id from apps_config.yaml — no need to specify a chat ID.

        Args:
            text:       Message text (up to 4096 characters).
            parse_mode: Optional formatting — 'HTML' or 'MarkdownV2'. Omit for plain text.
        """
        chat_id = CONFIG.app_data['default_chat_id']
        logger.info("Tool called: send_telegram_message_to_default chat_id=%s", chat_id)
        service = ApiServiceTelegramMessages(CONFIG)
        result = service.send_message(chat_id=chat_id, text=text, parse_mode=parse_mode)
        result = result if isinstance(result, dict) else {}
        logger.info("send_telegram_message_to_default sent message_id=%s", result.get("message_id"))
        return result

    @mcp.tool()
    def get_telegram_chat(chat_id: Any) -> dict:
        """Get metadata for a Telegram chat, group, or channel.

        Args:
            chat_id: Chat ID (integer) or public username (e.g. '@channel').
        """
        logger.info("Tool called: get_telegram_chat chat_id=%s", chat_id)
        service = ApiServiceTelegramMessages(CONFIG)
        result = service.get_chat(chat_id=chat_id)
        result = result if isinstance(result, dict) else {}
        logger.info("get_telegram_chat title=%s type=%s", result.get("title"), result.get("type"))
        return result
