import pytest
from hamcrest import assert_that, not_none, instance_of

from apps.trello.references.web.api.boards import ApiServiceTrelloBoards
from apps.trello.references.web.api.members import ApiServiceTrelloMembers
from apps.trello.config import CONFIG


@pytest.fixture()
def given():
    return ApiServiceTrelloMembers(CONFIG)


@pytest.fixture()
def first_board_id():
    boards = ApiServiceTrelloBoards(CONFIG).get_my_boards()
    if boards:
        return boards[0]['id']
    return None


@pytest.mark.smoke
def test_get_me(given):
    when = given.get_me()
    assert_that(when, instance_of(dict))
    assert_that(when.get('id'), not_none())
    assert_that(when.get('username'), not_none())


@pytest.mark.smoke
def test_get_member_boards(given):
    when = given.get_member_boards()
    assert_that(when, instance_of(list))


@pytest.mark.sanity
def test_get_board_members(given, first_board_id):
    if first_board_id is None:
        pytest.skip("No boards found")
    when = given.get_board_members(first_board_id)
    assert_that(when, instance_of(list))
