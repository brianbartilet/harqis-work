"""Offline regressions for credentials on a reused Trello service."""
from types import SimpleNamespace
from unittest.mock import Mock

from apps.trello.references.web.api.boards import ApiServiceTrelloBoards
from core.web.services.core.response import Response


def test_reused_board_service_authenticates_every_request():
    config = SimpleNamespace(client="rest", parameters={"base_url": "https://example.invalid"}, return_data_only=True,
                             app_data={"api_key": "test-key", "api_token": "test-token"})
    requests = []

    def execute(request):
        requests.append(request)
        return Response(dict, b"[]", "utf-8")

    service = ApiServiceTrelloBoards(config, client=Mock(execute_request=execute))
    for board in ("board-a", "board-b", "board-c"):
        assert service.get_board_lists(board) == []
        assert service.get_board_cards(board) == []

    assert len(requests) == 6
    for request in requests:
        assert request.query_string["key"] == "test-key"
        assert request.query_string["token"] == "test-token"
        assert request.query_string["filter"] == "open"
