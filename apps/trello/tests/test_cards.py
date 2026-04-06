import pytest
from hamcrest import assert_that, not_none, instance_of

from apps.trello.references.web.api.boards import ApiServiceTrelloBoards
from apps.trello.references.web.api.cards import ApiServiceTrelloCards
from apps.trello.config import CONFIG


@pytest.fixture()
def given():
    return ApiServiceTrelloCards(CONFIG)


@pytest.fixture()
def first_open_list_id():
    boards = ApiServiceTrelloBoards(CONFIG).get_my_boards()
    for board in boards:
        if board.get('closed'):
            continue
        lists = ApiServiceTrelloBoards(CONFIG).get_board_lists(board['id'])
        if lists:
            return lists[0]['id']
    return None


@pytest.mark.smoke
def test_get_list_cards(given, first_open_list_id):
    if first_open_list_id is None:
        pytest.skip("No open lists found")
    when = given.get_list_cards(first_open_list_id)
    assert_that(when, instance_of(list))


@pytest.mark.sanity
def test_create_and_archive_card(given, first_open_list_id):
    if first_open_list_id is None:
        pytest.skip("No open lists found")

    created = given.create_card(
        list_id=first_open_list_id,
        name='[TEST] harqis-work integration test',
        desc='Created by automated test — safe to delete'
    )
    assert_that(created, instance_of(dict))
    assert_that(created.get('id'), not_none())

    card_id = created['id']
    archived = ApiServiceTrelloCards(CONFIG).archive_card(card_id)
    assert_that(archived.get('closed'), not_none())
