import pytest
from hamcrest import assert_that, not_none, instance_of

from apps.telegram.references.web.api.messages import ApiServiceTelegramMessages
from apps.telegram.config import CONFIG


@pytest.fixture()
def given():
    return ApiServiceTelegramMessages(CONFIG)


@pytest.mark.smoke
def test_send_message(given):
    chat_id = CONFIG.app_data['default_chat_id']
    when = given.send_message(chat_id=chat_id, text='harqis-work MCP smoke test')
    assert_that(when, instance_of(dict))
    assert_that(when.get('message_id'), not_none())


@pytest.mark.smoke
def test_get_chat(given):
    chat_id = CONFIG.app_data['default_chat_id']
    when = given.get_chat(chat_id=chat_id)
    assert_that(when, instance_of(dict))
    assert_that(when.get('id'), not_none())
