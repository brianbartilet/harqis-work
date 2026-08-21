from http import HTTPStatus

import pytest

from apps.telegram.references.web.base_api_service import (
    BaseApiServiceTelegram,
    TelegramApiError,
)


class _Response:
    def __init__(self, status_code, data):
        self.status_code = status_code
        self.data = data


def _service_returning(response):
    service = object.__new__(BaseApiServiceTelegram)
    service._client = type("Client", (), {"execute_request": lambda self, request: response})()
    service._request = type("Request", (), {"build": lambda self: object()})()
    return service


@pytest.mark.parametrize(
    ("status_code", "data", "message"),
    [
        (HTTPStatus.UNAUTHORIZED, {"ok": False, "error_code": 401, "description": "Unauthorized"}, "401"),
        (HTTPStatus.OK, {"ok": False, "error_code": 400, "description": "Bad Request"}, "400"),
    ],
)
def test_execute_telegram_request_raises_for_api_errors(status_code, data, message):
    service = _service_returning(_Response(status_code, data))

    with pytest.raises(TelegramApiError, match=message):
        service.execute_telegram_request()


def test_execute_telegram_request_returns_success_response():
    response = _Response(HTTPStatus.OK, {"ok": True, "result": {"message_id": 42}})
    service = _service_returning(response)

    assert service.execute_telegram_request() is response
