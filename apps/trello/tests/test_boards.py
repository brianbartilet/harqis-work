import pytest
from hamcrest import assert_that, not_none, instance_of, greater_than_or_equal_to

from apps.trello.references.web.api.boards import ApiServiceTrelloBoards
from apps.trello.config import CONFIG


@pytest.fixture()
def given():
    return ApiServiceTrelloBoards(CONFIG)


@pytest.fixture()
def first_board_id():
    boards = ApiServiceTrelloBoards(CONFIG).get_my_boards()
    if boards:
        return boards[0]['id']
    return None


@pytest.mark.smoke
def test_get_my_boards(given):
    when = given.get_my_boards()
    assert_that(when, instance_of(list))
    assert_that(len(when), greater_than_or_equal_to(0))


@pytest.mark.smoke
def test_get_board(given, first_board_id):
    if first_board_id is None:
        pytest.skip("No boards found")
    when = given.get_board(first_board_id)
    assert_that(when, instance_of(dict))
    assert_that(when.get('id'), not_none())
    assert_that(when.get('name'), not_none())


@pytest.mark.sanity
def test_get_board_lists(given, first_board_id):
    if first_board_id is None:
        pytest.skip("No boards found")
    when = given.get_board_lists(first_board_id)
    assert_that(when, instance_of(list))


@pytest.mark.sanity
def test_get_board_cards(given, first_board_id):
    if first_board_id is None:
        pytest.skip("No boards found")
    when = given.get_board_cards(first_board_id)
    assert_that(when, instance_of(list))
