"""Exercise radar with real Trello request/deserializer, a fake HTTP transport."""
import json
from types import SimpleNamespace
from unittest.mock import Mock

from apps.trello.references.web.api.boards import ApiServiceTrelloBoards
from core.web.services.core.response import Response
from workflows.hud.tasks import daily_radar_agent as radar


def test_trello_radar_does_not_turn_missing_auth_into_json_errors(monkeypatch):
    config = SimpleNamespace(client="rest", parameters={"base_url": "https://example.invalid"},
                             return_data_only=True, app_data={"api_key": "test-key", "api_token": "test-token"})
    statuses = []

    def execute(request):
        authenticated = request.query_string.get("key") == "test-key" and request.query_string.get("token") == "test-token"
        if not authenticated:
            statuses.append(401)
            return Response(dict, b"invalid key", "utf-8")
        statuses.append(200)
        if request.full_uri.endswith("lists"):
            data = [{"id": "list-1", "name": "Ready"}]
        else:
            data = [{"idList": "list-1", "name": "Review", "shortUrl": "https://example.invalid/card"}]
        return Response(dict, json.dumps(data).encode(), "utf-8")

    service = ApiServiceTrelloBoards(config, client=Mock(execute_request=execute))
    monkeypatch.setattr(radar, "_resolve_trello_board_ids", lambda: ["board-a", "board-b", "board-c"])
    monkeypatch.setattr("apps.apps_config.CONFIG_MANAGER", Mock())
    monkeypatch.setattr("apps.trello.references.web.api.boards.ApiServiceTrelloBoards", lambda config: service)
    result = radar.collect_trello_cards()
    assert statuses == [200] * 6
    assert result["error"] is None
    assert [card["list"] for card in result["cards"]] == ["Ready"] * 3
