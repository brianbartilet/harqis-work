"""
DiscordPostTool — agent-facing tool for posting messages to Discord channels.

The tool is registered only when:
  - The workspace has a configured DiscordClient (DISCORD_BOT_TOKEN +
    DISCORD_GUILD_ID env vars set), AND
  - The profile declares at least one channel in
    `integrations.discord.allowed_channels`.

The agent picks the channel by inference. The tool's description embeds the
profile's `channel_hints` so Claude can reason about which channel suits the
current message. Channels not in the allowlist are rejected with a clear
error; the agent can then re-pick.
"""

from __future__ import annotations

import logging

from agents.projects.integrations.discord import DiscordClient, DiscordError
from agents.projects.profiles.schema import AgentProfile

logger = logging.getLogger(__name__)


class DiscordPostTool:
    """Posts agent output / artifacts to a Discord channel."""

    name = "discord_post"

    def __init__(self, client: DiscordClient, profile: AgentProfile):
        self._client = client
        # The allowlist is the source of truth for which channels this agent
        # may post to. Hints are advisory.
        self._allowed = list(profile.integrations.discord.allowed_channels)
        self._hints = dict(profile.integrations.discord.channel_hints)

    @property
    def description(self) -> str:
        lines = [
            "Post a message to a Discord channel for team visibility.",
            "Use this to broadcast results, surface artifacts, or alert the "
            "team about something that needs attention. The Trello card is "
            "still the system of record — Discord is for awareness, not for "
            "long-form deliverables.",
            "",
            "You may post to any of the following channels:",
        ]
        for ch in self._allowed:
            hint = self._hints.get(ch, "")
            lines.append(f"  - {ch}" + (f"  — {hint}" if hint else ""))
        lines.append("")
        lines.append(
            "Pick the channel whose purpose best matches the message. "
            "If unsure, prefer the more general channel."
        )
        return "\n".join(lines)

    @property
    def input_schema(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "channel": {
                    "type": "string",
                    "description": "Channel name (no leading '#'). Must be in the allowlist above.",
                    "enum": self._allowed,
                },
                "message": {
                    "type": "string",
                    "description": (
                        "Markdown content of the message. Discord caps a single "
                        "message at 2000 chars; longer content is auto-split."
                    ),
                },
            },
            "required": ["channel", "message"],
        }

    def run(self, channel: str, message: str) -> str:
        # The schema enum prevents disallowed channels from reaching here, but
        # double-check at runtime — schema validation isn't always enforced.
        if channel not in self._allowed:
            return (
                f"ERROR: channel '{channel}' is not in this agent's allowlist "
                f"({self._allowed})."
            )
        try:
            ids = self._client.post_message(channel, message)
        except DiscordError as e:
            logger.warning("DiscordPostTool failed: %s", e)
            return f"ERROR posting to Discord: {e}"
        return f"Posted to #{channel} ({len(ids)} message(s), id={ids[0] if ids else ''})"
