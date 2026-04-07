# Discord Integration

REST API client for the [Discord Bot API v10](https://discord.com/developers/docs/reference).

## What This Covers

- **Messaging** — send, fetch, edit, delete messages; send rich embeds; reply to messages
- **Reactions** — add/remove/list emoji reactions on messages
- **Guilds** — get server info, list channels, roles, and members
- **Webhooks** — create, execute, and manage incoming webhooks
- **Users** — get bot identity, list joined guilds, open DM channels

---

## Setup

### 1. Create a Discord Bot

1. Go to [Discord Developer Portal](https://discord.com/developers/applications)
2. **New Application** → name it → go to **Bot** tab
3. Click **Reset Token** and copy the token
4. Under **Privileged Gateway Intents**, enable:
   - `SERVER MEMBERS INTENT` (if using `list_members`)
   - `MESSAGE CONTENT INTENT` (if reading message content)
5. Go to **OAuth2 → URL Generator**:
   - Scopes: `bot`
   - Bot Permissions: `Send Messages`, `Read Message History`, `Add Reactions`, `Manage Webhooks`
6. Copy the generated URL, open it, and invite the bot to your server

### 2. Get IDs

Enable **Developer Mode** in Discord (Settings → Advanced → Developer Mode), then right-click any server or channel to **Copy ID**.

### 3. Configure `.env/apps.env`

```env
DISCORD_BOT_TOKEN=your-bot-token-here
DISCORD_DEFAULT_GUILD_ID=your-server-id
DISCORD_DEFAULT_CHANNEL_ID=your-channel-id
```

### 4. `apps_config.yaml` (already added)

```yaml
DISCORD:
  app_id: 'discord'
  client: 'rest'
  parameters:
    base_url: 'https://discord.com/api/v10/'
    timeout: 30
  app_data:
    bot_token: ${DISCORD_BOT_TOKEN}
    default_guild_id: ${DISCORD_DEFAULT_GUILD_ID}
    default_channel_id: ${DISCORD_DEFAULT_CHANNEL_ID}
  return_data_only: True
```

---

## API Reference

**Base URL:** `https://discord.com/api/v10/`
**Auth:** `Authorization: Bot <token>` + `User-Agent: DiscordBot (...)`

### Users (`ApiServiceDiscordUsers`)

| Method | Description |
|--------|-------------|
| `get_me()` | Get the current bot user |
| `get_user(user_id)` | Get any user by snowflake ID |
| `get_my_guilds(limit, before, after)` | List guilds the bot is in |
| `create_dm(recipient_id)` | Open a DM channel with a user |

### Messages (`ApiServiceDiscordMessages`)

| Method | Description |
|--------|-------------|
| `get_messages(channel_id, limit, before, after, around)` | Fetch messages from a channel |
| `get_message(channel_id, message_id)` | Fetch a single message |
| `send_message(channel_id, content, tts, flags)` | Send plain text |
| `send_embed(channel_id, embed, content)` | Send a rich embed card |
| `reply(channel_id, message_id, content, mention_author)` | Reply to a message |
| `edit_message(channel_id, message_id, content, embeds)` | Edit a bot message |
| `delete_message(channel_id, message_id)` | Delete a message |
| `add_reaction(channel_id, message_id, emoji)` | React to a message |
| `remove_reaction(channel_id, message_id, emoji)` | Remove own reaction |
| `get_reactions(channel_id, message_id, emoji, limit)` | Get users who reacted |

### Guilds (`ApiServiceDiscordGuilds`)

| Method | Description |
|--------|-------------|
| `get_guild(guild_id, with_counts)` | Guild info + member count |
| `get_channels(guild_id)` | All channels (excludes threads) |
| `get_member(guild_id, user_id)` | Single guild member |
| `list_members(guild_id, limit, after)` | Paginated member list (requires privileged intent) |
| `get_roles(guild_id)` | All roles |

### Webhooks (`ApiServiceDiscordWebhooks`)

| Method | Description |
|--------|-------------|
| `create_webhook(channel_id, name)` | Create an incoming webhook |
| `get_channel_webhooks(channel_id)` | List channel webhooks |
| `get_guild_webhooks(guild_id)` | List guild webhooks |
| `execute_webhook(webhook_id, token, content, embeds, ...)` | Post via webhook |
| `edit_webhook_message(webhook_id, token, message_id, ...)` | Edit a webhook message |
| `delete_webhook(webhook_id, token)` | Delete a webhook |

---

## Usage Examples

### Send a plain message

```python
from apps.discord.references.web.api.messages import ApiServiceDiscordMessages
from apps.discord.config import CONFIG

svc = ApiServiceDiscordMessages(CONFIG)
msg = svc.send_message(channel_id='123456789', content='Hello from HARQIS! 🤖')
print(msg['id'])
```

### Send an embed

```python
embed = {
    "title": "Daily Report",
    "description": "All systems nominal",
    "color": 0x00ff88,
    "fields": [
        {"name": "Tasks run", "value": "12", "inline": True},
        {"name": "Failures", "value": "0", "inline": True},
    ],
    "footer": {"text": "HARQIS-Work"},
    "timestamp": "2026-04-07T10:00:00.000Z",
}
svc.send_embed(channel_id='123456789', embed=embed)
```

### Reply to a message

```python
svc.reply(channel_id='123456789', message_id='987654321', content='Done ✅')
```

### React to a message

```python
svc.add_reaction(channel_id='123456789', message_id='987654321', emoji='👍')
```

### Execute a webhook (no bot token needed)

```python
from apps.discord.references.web.api.webhooks import ApiServiceDiscordWebhooks
from apps.discord.config import CONFIG

ApiServiceDiscordWebhooks(CONFIG).execute_webhook(
    webhook_id='111222333',
    webhook_token='abcdef...',
    content='Deployment complete 🚀',
    username='HARQIS Deploy',
)
```

### Get guild channels

```python
from apps.discord.references.web.api.guilds import ApiServiceDiscordGuilds
from apps.discord.config import CONFIG

channels = ApiServiceDiscordGuilds(CONFIG).get_channels(guild_id='555666777')
for ch in channels:
    print(ch['name'], ch['type'])
```

---

## Channel Type Reference

| Type | Name |
|------|------|
| 0 | Text |
| 1 | DM |
| 2 | Voice |
| 4 | Category |
| 5 | Announcement |
| 10-12 | Thread |
| 13 | Stage |
| 15 | Forum |

---

## Rate Limits

Discord enforces per-route and global rate limits:

- **Global:** 50 requests/second per bot
- **Per-route:** tracked via `X-RateLimit-Bucket` response header
- **429 response:** includes `retry_after` (float seconds) — wait before retrying

---

## Tests

```bash
# Requires DISCORD_BOT_TOKEN set in .env/apps.env
pytest apps/discord/tests/ -m smoke    # bot identity check
pytest apps/discord/tests/ -m sanity   # guild + channel tests (requires DISCORD_DEFAULT_GUILD_ID)
```

---

## MCP Tools

Registered in `mcp/server.py`. Available to Claude via the HARQIS-Work MCP server.

| Tool | Description |
|------|-------------|
| `get_discord_me` | Get current bot user info |
| `get_discord_my_guilds` | List all servers the bot is in |
| `get_discord_messages` | Fetch messages from a channel |
| `send_discord_message` | Send a text message to a channel |
| `send_discord_embed` | Send a rich embed to a channel |
| `send_discord_message_to_default` | Send to the configured default channel |
| `add_discord_reaction` | React to a message with an emoji |
| `get_discord_guild` | Get server info and member count |
| `get_discord_guild_channels` | List all channels in a server |
| `get_discord_guild_roles` | List all roles in a server |
| `execute_discord_webhook` | Post a message via webhook URL |

Example prompts:
- *"Send a status update to my Discord channel"* → `send_discord_message_to_default`
- *"What's in my Discord #general?"* → `get_discord_messages(channel_id='...')`
- *"List all channels in my server"* → `get_discord_guild_channels(guild_id='...')`
- *"Post a deployment notification via webhook"* → `execute_discord_webhook(...)`

---

## Privileged Intents

Some features require explicit enablement in the [Developer Portal](https://discord.com/developers/applications) → Bot settings:

| Intent | Required For |
|--------|-------------|
| `SERVER MEMBERS INTENT` | `list_members()` |
| `MESSAGE CONTENT INTENT` | Reading `content` field on messages not directed at the bot |

Bots in 100+ servers also require Discord's manual approval for these intents.

---

## Further Reading

- [Discord Developer Portal](https://discord.com/developers/applications)
- [Discord API Reference](https://discord.com/developers/docs/reference)
- [Bot Permissions Calculator](https://discordapi.com/permissions.html)
- [Discord API v10 Changelog](https://discord.com/developers/docs/change-log)
