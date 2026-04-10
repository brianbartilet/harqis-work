"""
Tests for the TrelloProvider adapter.
All HTTP calls are mocked — no real Trello API calls.
"""

import pytest
from unittest.mock import MagicMock, patch
from hamcrest import assert_that, equal_to, has_length, instance_of, contains_string

from agents.kanban.adapters.trello import TrelloProvider
from agents.kanban.interface import KanbanCard, KanbanColumn, KanbanChecklist


FAKE_KEY = "test_api_key"
FAKE_TOKEN = "test_token"
FAKE_BOARD_ID = "board123"


@pytest.fixture()
def provider():
    return TrelloProvider(api_key=FAKE_KEY, token=FAKE_TOKEN)


@pytest.fixture()
def mock_lists_response():
    return [
        {"id": "list_backlog", "name": "Backlog"},
        {"id": "list_claimed", "name": "Claimed"},
        {"id": "list_in_progress", "name": "In Progress"},
        {"id": "list_review", "name": "Review"},
        {"id": "list_done", "name": "Done"},
        {"id": "list_failed", "name": "Failed"},
    ]


@pytest.fixture()
def mock_card_response():
    return {
        "id": "card_abc",
        "name": "Write a test",
        "desc": "Create a pytest test file",
        "idBoard": FAKE_BOARD_ID,
        "idList": "list_backlog",
        "idMembers": [],
        "labels": [{"id": "lbl1", "name": "agent:code"}],
        "due": None,
        "shortUrl": "https://trello.com/c/abc",
        "checklists": [
            {
                "id": "cl1",
                "name": "Steps",
                "checkItems": [
                    {"id": "ci1", "name": "Read code", "state": "incomplete"},
                    {"id": "ci2", "name": "Write test", "state": "complete"},
                ],
            }
        ],
        "attachments": [],
        "customFieldItems": [],
    }


@pytest.mark.smoke
def test_get_columns(provider, mock_lists_response):
    with patch("requests.get") as mock_get:
        mock_get.return_value.status_code = 200
        mock_get.return_value.json.return_value = mock_lists_response
        mock_get.return_value.raise_for_status = MagicMock()

        columns = provider.get_columns(FAKE_BOARD_ID)

        assert_that(columns, has_length(6))
        names = [c.name for c in columns]
        assert_that("Backlog" in names, equal_to(True))
        assert_that("Done" in names, equal_to(True))


@pytest.mark.smoke
def test_get_column_by_name(provider, mock_lists_response):
    with patch("requests.get") as mock_get:
        mock_get.return_value.status_code = 200
        mock_get.return_value.json.return_value = mock_lists_response
        mock_get.return_value.raise_for_status = MagicMock()

        col = provider.get_column_by_name(FAKE_BOARD_ID, "Backlog")

        assert_that(col, instance_of(KanbanColumn))
        assert_that(col.name, equal_to("Backlog"))
        assert_that(col.id, equal_to("list_backlog"))


@pytest.mark.smoke
def test_get_column_by_name_missing(provider, mock_lists_response):
    with patch("requests.get") as mock_get:
        mock_get.return_value.json.return_value = mock_lists_response
        mock_get.return_value.raise_for_status = MagicMock()

        col = provider.get_column_by_name(FAKE_BOARD_ID, "NonExistent")

        assert_that(col, equal_to(None))


@pytest.mark.smoke
def test_get_cards_maps_correctly(provider, mock_lists_response, mock_card_response):
    with patch("requests.get") as mock_get:
        mock_get.return_value.json.side_effect = [
            mock_lists_response,           # get_columns call
            [mock_card_response],          # get list cards
        ]
        mock_get.return_value.raise_for_status = MagicMock()

        cards = provider.get_cards(FAKE_BOARD_ID, "Backlog")

        assert_that(cards, has_length(1))
        card = cards[0]
        assert_that(card, instance_of(KanbanCard))
        assert_that(card.id, equal_to("card_abc"))
        assert_that(card.title, equal_to("Write a test"))
        assert_that(card.labels, equal_to(["agent:code"]))
        assert_that(card.checklists, has_length(1))
        assert_that(card.checklists[0].items, has_length(2))


@pytest.mark.smoke
def test_get_cards_filters_by_label(provider, mock_lists_response, mock_card_response):
    with patch("requests.get") as mock_get:
        mock_get.return_value.json.side_effect = [
            mock_lists_response,
            [mock_card_response],
        ]
        mock_get.return_value.raise_for_status = MagicMock()

        cards_match = provider.get_cards(FAKE_BOARD_ID, "Backlog", label="agent:code")
        assert_that(cards_match, has_length(1))

    with patch("requests.get") as mock_get:
        mock_get.return_value.json.side_effect = [
            mock_lists_response,
            [mock_card_response],
        ]
        mock_get.return_value.raise_for_status = MagicMock()

        cards_no_match = provider.get_cards(FAKE_BOARD_ID, "Backlog", label="agent:write")
        assert_that(cards_no_match, has_length(0))


@pytest.mark.smoke
def test_checklist_item_state_mapping(provider, mock_lists_response, mock_card_response):
    with patch("requests.get") as mock_get:
        mock_get.return_value.json.side_effect = [
            mock_lists_response,
            [mock_card_response],
        ]
        mock_get.return_value.raise_for_status = MagicMock()

        cards = provider.get_cards(FAKE_BOARD_ID, "Backlog")
        items = cards[0].checklists[0].items

        assert_that(items[0].checked, equal_to(False))   # incomplete
        assert_that(items[1].checked, equal_to(True))    # complete


@pytest.mark.smoke
def test_add_comment_calls_correct_endpoint(provider):
    with patch("requests.post") as mock_post:
        mock_post.return_value.raise_for_status = MagicMock()

        provider.add_comment("card_abc", "Hello from agent")

        mock_post.assert_called_once()
        call_args = mock_post.call_args
        assert_that(str(call_args), contains_string("card_abc"))
        assert_that(str(call_args), contains_string("comments"))


@pytest.mark.smoke
def test_move_card(provider, mock_lists_response):
    card_data = {"id": "card_abc", "idBoard": FAKE_BOARD_ID}
    with patch("requests.get") as mock_get, patch("requests.put") as mock_put:
        mock_get.return_value.json.side_effect = [card_data, mock_lists_response]
        mock_get.return_value.raise_for_status = MagicMock()
        mock_put.return_value.raise_for_status = MagicMock()

        provider.move_card("card_abc", "In Progress")

        mock_put.assert_called_once()
        params = mock_put.call_args.kwargs.get("params", {})
        assert_that(params.get("idList"), equal_to("list_in_progress"))


@pytest.mark.integration
def test_live_get_columns():
    """Integration: requires TRELLO_API_KEY and TRELLO_API_TOKEN in env."""
    import os
    provider = TrelloProvider(
        api_key=os.environ["TRELLO_API_KEY"],
        token=os.environ["TRELLO_API_TOKEN"],
    )
    board_id = os.environ["KANBAN_BOARD_ID"]
    columns = provider.get_columns(board_id)
    assert_that(len(columns) > 0, equal_to(True))
