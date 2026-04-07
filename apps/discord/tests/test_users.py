import pytest
from hamcrest import assert_that, instance_of, has_key, not_none, greater_than_or_equal_to

from apps.discord.references.web.api.users import ApiServiceDiscordUsers
from apps.discord.config import CONFIG


def _require_token():
    if not CONFIG.app_data.get('bot_token'):
        pytest.skip("DISCORD_BOT_TOKEN not configured in .env/apps.env")


@pytest.fixture()
def given():
    _require_token()
    return ApiServiceDiscordUsers(CONFIG)


@pytest.mark.smoke
def test_get_me(given):
    """Bot token is valid and returns current user info."""
    when = given.get_me()
    assert_that(when, instance_of(dict))
    assert_that(when, has_key('id'))
    assert_that(when, has_key('username'))
    assert_that(when.get('bot'), not_none())


@pytest.mark.smoke
def test_get_my_guilds(given):
    """Bot can list guilds it belongs to."""
    when = given.get_my_guilds()
    assert_that(when, instance_of(list))
    assert_that(len(when), greater_than_or_equal_to(0))


@pytest.mark.sanity
def test_get_user(given):
    """Bot can look up its own user ID."""
    me = ApiServiceDiscordUsers(CONFIG).get_me()
    if not isinstance(me, dict) or not me.get('id'):
        pytest.skip("Could not retrieve bot user ID")
    when = ApiServiceDiscordUsers(CONFIG).get_user(me['id'])
    assert_that(when, instance_of(dict))
    assert_that(when, has_key('username'))
