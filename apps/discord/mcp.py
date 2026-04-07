import logging
from typing import Optional

from mcp.server.fastmcp import FastMCP
from apps.discord.config import CONFIG
from apps.discord.references.web.api.users import ApiServiceDiscordUsers
from apps.discord.references.web.api.messages import ApiServiceDiscordMessages
from apps.discord.references.web.api.guilds import ApiServiceDiscordGuilds
from apps.discord.references.web.api.webhooks import ApiServiceDiscordWebhooks

logger = logging.getLogger("harqis-mcp.discord")


def register_discord_tools(mcp: FastMCP):

    # ── Users ─────────────────────────────────────────────────────────────

    @mcp.tool()
    def get_discord_me() -> dict:
        """Get the current Discord bot user info (username, ID, avatar).

        Returns:
            Bot User object with id, username, discriminator, bot flag.
        """
        logger.info("Tool called: get_discord_me")
        result = ApiServiceDiscordUsers(CONFIG).get_me()
        return result if isinstance(result, dict) else {}

    @mcp.tool()
    def get_discord_my_guilds() -> list[dict]:
        """List all Discord servers (guilds) the bot belongs to.

        Returns:
            List of partial Guild objects with id, name, icon, permissions.
        """
        logger.info("Tool called: get_discord_my_guilds")
        result = ApiServiceDiscordUsers(CONFIG).get_my_guilds()
        return result if isinstance(result, list) else []

    # ── Messages ──────────────────────────────────────────────────────────

    @mcp.tool()
    def get_discord_messages(channel_id: str, limit: int = 20) -> list[dict]:
        """Get recent messages from a Discord channel.

        Args:
            channel_id: Channel snowflake ID.
            limit:      Number of messages to fetch (1–100). Default 20.

        Returns:
            List of Message objects, most recent first.
        """
        logger.info("Tool called: get_discord_messages channel=%s", channel_id)
        result = ApiServiceDiscordMessages(CONFIG).get_messages(channel_id, limit=limit)
        return result if isinstance(result, list) else []

    @mcp.tool()
    def send_discord_message(channel_id: str, content: str) -> dict:
        """Send a text message to a Discord channel.

        Args:
            channel_id: Channel snowflake ID.
            content:    Message text (max 2000 characters).

        Returns:
            Created Message object with id, content, timestamp.
        """
        logger.info("Tool called: send_discord_message channel=%s", channel_id)
        result = ApiServiceDiscordMessages(CONFIG).send_message(channel_id, content)
        return result if isinstance(result, dict) else {}

    @mcp.tool()
    def send_discord_embed(channel_id: str, title: str, description: str,
                           color: int = 0x5865F2, content: str = None) -> dict:
        """Send an embed (rich card) message to a Discord channel.

        Args:
            channel_id:  Channel snowflake ID.
            title:       Embed title (max 256 chars).
            description: Embed body text (max 4096 chars).
            color:       Sidebar color as integer (default Discord blurple 0x5865F2).
            content:     Optional plain text above the embed.

        Returns:
            Created Message object.
        """
        logger.info("Tool called: send_discord_embed channel=%s title=%s", channel_id, title)
        embed = {"title": title, "description": description, "color": color}
        result = ApiServiceDiscordMessages(CONFIG).send_embed(channel_id, embed, content)
        return result if isinstance(result, dict) else {}

    @mcp.tool()
    def send_discord_message_to_default(content: str) -> dict:
        """Send a text message to the configured default Discord channel.

        Uses DISCORD_DEFAULT_CHANNEL_ID from environment config.

        Args:
            content: Message text (max 2000 characters).
        """
        channel_id = CONFIG.app_data.get('default_channel_id', '')
        if not channel_id:
            return {"error": "DISCORD_DEFAULT_CHANNEL_ID not configured"}
        logger.info("Tool called: send_discord_message_to_default")
        result = ApiServiceDiscordMessages(CONFIG).send_message(channel_id, content)
        return result if isinstance(result, dict) else {}

    @mcp.tool()
    def add_discord_reaction(channel_id: str, message_id: str, emoji: str) -> dict:
        """Add a reaction emoji to a Discord message.

        Args:
            channel_id: Channel containing the message.
            message_id: Message snowflake ID.
            emoji:      Unicode emoji (e.g. '👍') or custom emoji 'name:id'.
        """
        logger.info("Tool called: add_discord_reaction channel=%s msg=%s emoji=%s",
                    channel_id, message_id, emoji)
        ApiServiceDiscordMessages(CONFIG).add_reaction(channel_id, message_id, emoji)
        return {"status": "ok"}

    # ── Guilds ────────────────────────────────────────────────────────────

    @mcp.tool()
    def get_discord_guild(guild_id: str) -> dict:
        """Get Discord server (guild) info including name, members, and roles.

        Args:
            guild_id: Guild snowflake ID.

        Returns:
            Guild object with name, owner_id, approximate_member_count, roles, features.
        """
        logger.info("Tool called: get_discord_guild guild=%s", guild_id)
        result = ApiServiceDiscordGuilds(CONFIG).get_guild(guild_id)
        return result if isinstance(result, dict) else {}

    @mcp.tool()
    def get_discord_guild_channels(guild_id: str) -> list[dict]:
        """List all channels in a Discord server.

        Args:
            guild_id: Guild snowflake ID.

        Returns:
            List of Channel objects with id, name, type, topic, position.
            Channel types: 0=text, 2=voice, 4=category, 5=announcement, 13=stage, 15=forum.
        """
        logger.info("Tool called: get_discord_guild_channels guild=%s", guild_id)
        result = ApiServiceDiscordGuilds(CONFIG).get_channels(guild_id)
        return result if isinstance(result, list) else []

    @mcp.tool()
    def get_discord_guild_roles(guild_id: str) -> list[dict]:
        """List all roles in a Discord server.

        Args:
            guild_id: Guild snowflake ID.

        Returns:
            List of Role objects with id, name, color, permissions, position.
        """
        logger.info("Tool called: get_discord_guild_roles guild=%s", guild_id)
        result = ApiServiceDiscordGuilds(CONFIG).get_roles(guild_id)
        return result if isinstance(result, list) else []

    # ── Webhooks ──────────────────────────────────────────────────────────

    @mcp.tool()
    def execute_discord_webhook(webhook_id: str, webhook_token: str,
                                content: str = None, username: str = None,
                                title: str = None, description: str = None) -> dict:
        """Send a message via a Discord webhook URL.

        Does not require bot token — uses the webhook's own token.
        Useful for sending notifications from external systems.

        Args:
            webhook_id:    Webhook snowflake ID.
            webhook_token: Webhook token (from the webhook URL).
            content:       Plain text message (max 2000 chars).
            username:      Override the webhook's display name.
            title:         Optional embed title (creates an embed alongside content).
            description:   Optional embed description.

        Returns:
            Created Message object.
        """
        logger.info("Tool called: execute_discord_webhook webhook=%s", webhook_id)
        embeds = None
        if title or description:
            embeds = [{"title": title or "", "description": description or ""}]
        result = ApiServiceDiscordWebhooks(CONFIG).execute_webhook(
            webhook_id=webhook_id,
            webhook_token=webhook_token,
            content=content,
            username=username,
            embeds=embeds,
        )
        return result if isinstance(result, dict) else {}
