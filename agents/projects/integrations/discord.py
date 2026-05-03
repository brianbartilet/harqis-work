"""
Discord integration — post agent output to Discord channels via Bot API.

The agent decides which channel to post to by inference, scoped to a
per-profile allowlist (see `IntegrationsConfig.discord`):

  Profile YAML
    integrations:
      discord:
        allowed_channels: [engineering, content, ops-alerts]
        channel_hints:
          engineering: "Code reviews, PR notifications, build/test status"
          content:     "Article drafts, copy reviews, marketing assets"
          ops-alerts:  "Operational issues, blocked deployments"

  Agent at runtime calls the `discord_post` tool with `(channel, message)`.
  The tool validates `channel` against the profile's allowlist, resolves
  the channel name → channel ID via the Bot API, then POSTs the message.

Workspace-level configuration (one bot, all agents):
  DISCORD_BOT_TOKEN  — Discord bot token (Bot API auth header)
  DISCORD_GUILD_ID   — Discord server (guild) ID

When either env var is absent the tool is silently not registered for any
agent; profiles can still declare `allowed_channels`, but `discord_post`
won't appear in their tool inventory.
"""

from __future__ import annotations

import logging
import os
from typing import Optional

import requests

logger = logging.getLogger(__name__)

_BASE = "https://discord.com/api/v10"


class DiscordError(RuntimeError):
    """Raised by DiscordClient on API errors or configuration problems."""


class DiscordClient:
    """Thin wrapper around Discord Bot API for posting messages.

    One client per workspace orchestrator — the Mode A profile-client
    pattern from Trello does not apply here (Discord uses one bot regardless
    of which agent is posting; persona is conveyed in-message).
    """

    def __init__(self, bot_token: str, guild_id: str, timeout: int = 10):
        if not bot_token:
            raise DiscordError("bot_token is required")
        if not guild_id:
            raise DiscordError("guild_id is required")
        self._bot_token = bot_token
        self._guild_id = guild_id
        self._timeout = timeout
        # channel_name → channel_id, populated lazily.
        self._channel_cache: dict[str, str] = {}

    @classmethod
    def from_env(cls) -> Optional["DiscordClient"]:
        """Build from `DISCORD_BOT_TOKEN` + `DISCORD_GUILD_ID`. Return None
        when either is unset — caller should treat that as "Discord disabled"
        and skip tool registration / orchestrator-level posts."""
        token = os.environ.get("DISCORD_BOT_TOKEN")
        guild = os.environ.get("DISCORD_GUILD_ID")
        if not token or not guild:
            return None
        return cls(bot_token=token, guild_id=guild)

    # ── HTTP plumbing ────────────────────────────────────────────────────────

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bot {self._bot_token}",
            "Content-Type": "application/json",
            # Discord asks for a User-Agent identifying the bot.
            "User-Agent": "harqis-projects-orchestrator (https://github.com/brianbartilet/harqis-work, 1.0)",
        }

    # ── Channel resolution ───────────────────────────────────────────────────

    def _refresh_channels(self) -> dict[str, str]:
        """Fetch every channel in the guild and rebuild the name→id cache.

        Discord channel names are unique within a category but NOT globally
        unique within a guild. We index by bare name; if duplicates exist,
        the last one wins (text channels normally don't collide because the
        Discord UI surfaces collisions to the user creating them).
        """
        url = f"{_BASE}/guilds/{self._guild_id}/channels"
        r = requests.get(url, headers=self._headers(), timeout=self._timeout)
        if r.status_code >= 400:
            raise DiscordError(
                f"Failed to list channels for guild {self._guild_id} "
                f"({r.status_code}): {r.text}"
            )
        # Filter to text-ish channels: 0=GUILD_TEXT, 5=GUILD_ANNOUNCEMENT,
        # 10/11/12=public/private/announcement threads, 15=GUILD_FORUM.
        text_types = {0, 5, 10, 11, 12, 15}
        mapping = {
            ch["name"]: ch["id"]
            for ch in r.json()
            if ch.get("type") in text_types
        }
        self._channel_cache = mapping
        return mapping

    def resolve_channel(self, name: str) -> str:
        """Return the channel ID for a channel name. Refreshes the cache once
        on miss so newly created channels are picked up without a restart."""
        # Strip a leading `#` so `#engineering` and `engineering` both work.
        name = name.lstrip("#")
        if name in self._channel_cache:
            return self._channel_cache[name]
        self._refresh_channels()
        if name not in self._channel_cache:
            raise DiscordError(
                f"Channel '{name}' not found in guild {self._guild_id} "
                f"(known: {sorted(self._channel_cache.keys())})"
            )
        return self._channel_cache[name]

    def list_channels(self) -> list[str]:
        """Return all known text-channel names. Triggers a refresh on first call."""
        if not self._channel_cache:
            self._refresh_channels()
        return sorted(self._channel_cache.keys())

    # ── Posting ──────────────────────────────────────────────────────────────

    # Discord caps a single message at 2000 chars. Longer messages are split.
    MAX_MESSAGE_LEN = 2000

    def post_message(self, channel: str, content: str) -> list[str]:
        """Post a message to a channel. Returns the list of message IDs created
        (always ≥1; >1 when content was split into multiple Discord messages).

        Raises DiscordError on any non-2xx response.
        """
        channel_id = self.resolve_channel(channel)
        url = f"{_BASE}/channels/{channel_id}/messages"

        chunks = self._split(content) if content else [""]
        ids: list[str] = []
        for chunk in chunks:
            r = requests.post(
                url,
                headers=self._headers(),
                json={"content": chunk},
                timeout=self._timeout,
            )
            if r.status_code >= 400:
                raise DiscordError(
                    f"POST to channel '{channel}' failed ({r.status_code}): {r.text}"
                )
            ids.append(r.json().get("id", ""))
        return ids

    @classmethod
    def _split(cls, content: str) -> list[str]:
        """Split content into chunks ≤ MAX_MESSAGE_LEN, preferring line breaks."""
        if len(content) <= cls.MAX_MESSAGE_LEN:
            return [content]
        chunks: list[str] = []
        remaining = content
        while len(remaining) > cls.MAX_MESSAGE_LEN:
            cut = remaining.rfind("\n", 0, cls.MAX_MESSAGE_LEN)
            if cut <= 0:
                cut = cls.MAX_MESSAGE_LEN
            chunks.append(remaining[:cut])
            remaining = remaining[cut:].lstrip("\n")
        if remaining:
            chunks.append(remaining)
        return chunks
