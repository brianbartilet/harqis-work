import pytest
from hamcrest import assert_that, instance_of, has_key, greater_than_or_equal_to

from apps.discord.references.web.api.messages import ApiServiceDiscordMessages
from apps.discord.config import CONFIG


def _require_token():
    if not CONFIG.app_data.get('bot_token'):
        pytest.skip("DISCORD_BOT_TOKEN not configured in .env/apps.env")


def _require_channel():
    _require_token()
    channel_id = CONFIG.app_data.get('default_channel_id')
    if not channel_id:
        pytest.skip("DISCORD_DEFAULT_CHANNEL_ID not configured in .env/apps.env")
    return channel_id


@pytest.fixture()
def channel_id():
    return _require_channel()


@pytest.mark.smoke
def test_get_messages(channel_id):
    """Fetches messages from the default channel."""
    when = ApiServiceDiscordMessages(CONFIG).get_messages(channel_id, limit=10)
    assert_that(when, instance_of(list))
    assert_that(len(when), greater_than_or_equal_to(0))


@pytest.mark.sanity
def test_send_and_get_message(channel_id):
    """Sends a test message and retrieves it."""
    svc = ApiServiceDiscordMessages(CONFIG)
    sent = svc.send_message(channel_id, content="[harqis-work test] smoke check 🤖")
    assert_that(sent, instance_of(dict))
    assert_that(sent, has_key('id'))

    fetched = ApiServiceDiscordMessages(CONFIG).get_message(channel_id, sent['id'])
    assert_that(fetched, instance_of(dict))
    assert_that(fetched.get('id'), not None)


@pytest.mark.sanity
def test_send_embed(channel_id):
    """Sends an embed message."""
    embed = {
        "title": "harqis-work test",
        "description": "Embed smoke check",
        "color": 0x00aaff,
    }
    when = ApiServiceDiscordMessages(CONFIG).send_embed(channel_id, embed=embed)
    assert_that(when, instance_of(dict))
    assert_that(when, has_key('id'))
