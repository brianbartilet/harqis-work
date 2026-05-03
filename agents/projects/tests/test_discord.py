"""
Tests for the Discord integration: client + agent tool.

All HTTP calls are mocked — no real Discord API traffic.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from hamcrest import assert_that, contains_string, equal_to, has_length

from agents.projects.agent.tools.discord_tool import DiscordPostTool
from agents.projects.integrations.discord import DiscordClient, DiscordError
from agents.projects.profiles.schema import (
    AgentProfile,
    DiscordIntegration,
    IntegrationsConfig,
)


# ── DiscordClient ────────────────────────────────────────────────────────────

@pytest.mark.smoke
def test_client_requires_token_and_guild():
    with pytest.raises(DiscordError):
        DiscordClient(bot_token="", guild_id="g")
    with pytest.raises(DiscordError):
        DiscordClient(bot_token="t", guild_id="")


@pytest.mark.smoke
def test_from_env_returns_none_when_unconfigured(monkeypatch):
    monkeypatch.delenv("DISCORD_BOT_TOKEN", raising=False)
    monkeypatch.delenv("DISCORD_GUILD_ID", raising=False)
    assert_that(DiscordClient.from_env(), equal_to(None))


@pytest.mark.smoke
def test_from_env_builds_client_when_configured(monkeypatch):
    monkeypatch.setenv("DISCORD_BOT_TOKEN", "tok")
    monkeypatch.setenv("DISCORD_GUILD_ID", "guild123")
    client = DiscordClient.from_env()
    assert_that(client is None, equal_to(False))


def _channels_response(channels):
    """Build a fake `requests.Response` for GET /guilds/{id}/channels."""
    r = MagicMock()
    r.status_code = 200
    r.json.return_value = channels
    return r


def _post_response(message_id="msg1", status_code=200):
    r = MagicMock()
    r.status_code = status_code
    r.json.return_value = {"id": message_id}
    r.text = ""
    return r


@pytest.mark.smoke
def test_resolve_channel_filters_to_text_types():
    """Voice channels (type=2) and categories (type=4) must NOT show up."""
    fake = _channels_response([
        {"id": "c1", "name": "general",   "type": 0},   # text
        {"id": "c2", "name": "voice-1",   "type": 2},   # voice — must skip
        {"id": "c3", "name": "ANNOUNCE",  "type": 5},   # announcement — keep
        {"id": "c4", "name": "category",  "type": 4},   # category — must skip
        {"id": "c5", "name": "thread",    "type": 11},  # thread — keep
    ])
    with patch("agents.projects.integrations.discord.requests.get", return_value=fake):
        client = DiscordClient(bot_token="t", guild_id="g")
        names = client.list_channels()
    assert_that(set(names), equal_to({"general", "ANNOUNCE", "thread"}))


@pytest.mark.smoke
def test_resolve_channel_strips_leading_hash():
    fake = _channels_response([{"id": "c1", "name": "engineering", "type": 0}])
    with patch("agents.projects.integrations.discord.requests.get", return_value=fake):
        client = DiscordClient(bot_token="t", guild_id="g")
        # `#engineering` and `engineering` should both resolve.
        assert_that(client.resolve_channel("#engineering"), equal_to("c1"))
        assert_that(client.resolve_channel("engineering"), equal_to("c1"))


@pytest.mark.smoke
def test_resolve_channel_unknown_raises():
    fake = _channels_response([{"id": "c1", "name": "general", "type": 0}])
    with patch("agents.projects.integrations.discord.requests.get", return_value=fake):
        client = DiscordClient(bot_token="t", guild_id="g")
        with pytest.raises(DiscordError):
            client.resolve_channel("nonexistent")


@pytest.mark.smoke
def test_post_message_short_sends_one_request():
    fake_channels = _channels_response([{"id": "c1", "name": "general", "type": 0}])
    fake_post = _post_response("msg-abc")

    with patch("agents.projects.integrations.discord.requests.get", return_value=fake_channels), \
         patch("agents.projects.integrations.discord.requests.post", return_value=fake_post) as mp:
        client = DiscordClient(bot_token="tok", guild_id="g")
        ids = client.post_message("general", "hello")

    assert_that(ids, equal_to(["msg-abc"]))
    # Auth header is "Bot <token>" per Discord spec.
    assert_that(mp.call_args.kwargs["headers"]["Authorization"], equal_to("Bot tok"))
    assert_that(mp.call_args.kwargs["json"]["content"], equal_to("hello"))


@pytest.mark.smoke
def test_post_message_splits_long_content():
    """Discord caps a single message at 2000 chars; the client splits longer ones."""
    fake_channels = _channels_response([{"id": "c1", "name": "general", "type": 0}])
    fake_post = _post_response()

    long_content = "line\n" * 600  # 3000 chars

    with patch("agents.projects.integrations.discord.requests.get", return_value=fake_channels), \
         patch("agents.projects.integrations.discord.requests.post", return_value=fake_post) as mp:
        client = DiscordClient(bot_token="t", guild_id="g")
        ids = client.post_message("general", long_content)

    # Should have split into >1 chunk.
    assert_that(len(ids) >= 2, equal_to(True))
    assert_that(mp.call_count, equal_to(len(ids)))
    # Every chunk must fit Discord's limit.
    for call in mp.call_args_list:
        assert_that(len(call.kwargs["json"]["content"]) <= DiscordClient.MAX_MESSAGE_LEN,
                    equal_to(True))


@pytest.mark.smoke
def test_post_message_raises_on_4xx():
    fake_channels = _channels_response([{"id": "c1", "name": "general", "type": 0}])
    fake_post = _post_response(status_code=403)
    fake_post.text = "Forbidden"

    with patch("agents.projects.integrations.discord.requests.get", return_value=fake_channels), \
         patch("agents.projects.integrations.discord.requests.post", return_value=fake_post):
        client = DiscordClient(bot_token="t", guild_id="g")
        with pytest.raises(DiscordError):
            client.post_message("general", "blocked")


# ── DiscordPostTool ──────────────────────────────────────────────────────────

def _profile_with_channels(channels, hints=None) -> AgentProfile:
    return AgentProfile(
        id="agent:test",
        name="Test",
        integrations=IntegrationsConfig(
            discord=DiscordIntegration(
                allowed_channels=channels,
                channel_hints=hints or {},
            ),
        ),
    )


@pytest.mark.smoke
def test_tool_description_lists_allowed_channels_and_hints():
    profile = _profile_with_channels(
        ["engineering", "content"],
        hints={"engineering": "Code reviews", "content": "Articles"},
    )
    tool = DiscordPostTool(client=MagicMock(), profile=profile)
    desc = tool.description
    assert_that(desc, contains_string("engineering"))
    assert_that(desc, contains_string("Code reviews"))
    assert_that(desc, contains_string("content"))
    assert_that(desc, contains_string("Articles"))


@pytest.mark.smoke
def test_tool_input_schema_enum_matches_allowlist():
    profile = _profile_with_channels(["engineering", "ops-alerts"])
    tool = DiscordPostTool(client=MagicMock(), profile=profile)
    assert_that(tool.input_schema["properties"]["channel"]["enum"],
                equal_to(["engineering", "ops-alerts"]))


@pytest.mark.smoke
def test_tool_rejects_disallowed_channel():
    """Even if Claude bypasses the schema enum, the runtime check catches it."""
    profile = _profile_with_channels(["engineering"])
    fake_client = MagicMock()
    tool = DiscordPostTool(client=fake_client, profile=profile)

    result = tool.run(channel="exec", message="hi")
    assert_that(result, contains_string("not in this agent's allowlist"))
    fake_client.post_message.assert_not_called()


@pytest.mark.smoke
def test_tool_calls_client_when_channel_allowed():
    profile = _profile_with_channels(["engineering"])
    fake_client = MagicMock()
    fake_client.post_message.return_value = ["m1"]
    tool = DiscordPostTool(client=fake_client, profile=profile)

    result = tool.run(channel="engineering", message="hello team")
    fake_client.post_message.assert_called_once_with("engineering", "hello team")
    assert_that(result, contains_string("Posted to #engineering"))


@pytest.mark.smoke
def test_tool_returns_error_string_on_discord_failure():
    """When the client raises, the tool should return an ERROR string rather
    than raise — the agent then sees the failure as a tool result and can
    decide whether to retry, switch channels, or stop."""
    profile = _profile_with_channels(["engineering"])
    fake_client = MagicMock()
    fake_client.post_message.side_effect = DiscordError("rate limited")
    tool = DiscordPostTool(client=fake_client, profile=profile)

    result = tool.run(channel="engineering", message="x")
    assert_that(result, contains_string("ERROR posting to Discord"))
    assert_that(result, contains_string("rate limited"))
