import pytest
from hamcrest import assert_that, instance_of, has_key, greater_than_or_equal_to, not_none

from apps.discord.references.web.api.users import ApiServiceDiscordUsers
from apps.discord.references.web.api.guilds import ApiServiceDiscordGuilds
from apps.discord.config import CONFIG


def _require_token():
    if not CONFIG.app_data.get('bot_token'):
        pytest.skip("DISCORD_BOT_TOKEN not configured in .env/apps.env")


@pytest.fixture()
def default_guild_id():
    _require_token()
    guild_id = CONFIG.app_data.get('default_guild_id')
    if not guild_id:
        guilds = ApiServiceDiscordUsers(CONFIG).get_my_guilds(limit=1)
        if isinstance(guilds, list) and guilds:
            return guilds[0]['id']
        pytest.skip("No guild available — set DISCORD_DEFAULT_GUILD_ID or add the bot to a server")
    return guild_id


@pytest.mark.smoke
def test_get_guild(default_guild_id):
    """Fetches guild info including member count."""
    when = ApiServiceDiscordGuilds(CONFIG).get_guild(default_guild_id)
    assert_that(when, instance_of(dict))
    assert_that(when, has_key('id'))
    assert_that(when, has_key('name'))


@pytest.mark.sanity
def test_get_guild_channels(default_guild_id):
    """Returns list of channels in the guild."""
    when = ApiServiceDiscordGuilds(CONFIG).get_channels(default_guild_id)
    assert_that(when, instance_of(list))
    assert_that(len(when), greater_than_or_equal_to(0))


@pytest.mark.sanity
def test_get_guild_roles(default_guild_id):
    """Returns list of roles in the guild."""
    when = ApiServiceDiscordGuilds(CONFIG).get_roles(default_guild_id)
    assert_that(when, instance_of(list))
    assert_that(len(when), greater_than_or_equal_to(1))
