# Telegram Integration

Telegram Bot API services and MCP tools for bot identity, updates, messages,
and chat details.

## Setup

Set `TELEGRAM_BOT_TOKEN` and `TELEGRAM_DEFAULT_CHAT_ID` in `.env/apps.env`. The
`TELEGRAM` block in `apps_config.yaml` targets `https://api.telegram.org/`.

## MCP tools

`get_telegram_bot_info`, `get_telegram_updates`, `send_telegram_message`,
`send_telegram_message_to_default`, and `get_telegram_chat` are registered by
`register_telegram_tools()` in `mcp/server.py`.

## Testing

```powershell
pytest apps/telegram/tests
```

Tests use the live bot. Message tests post to the configured chat, so confirm
the destination before running them. Never log or commit the bot token.
