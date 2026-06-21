import pytest


def skip_if_telegram_auth_error(response: object) -> None:
    data = getattr(response, "data", None)
    status_code = getattr(response, "status_code", None)
    if isinstance(data, dict) and (status_code == 401 or data.get("error_code") == 401):
        pytest.skip(f"Telegram Bot API unauthorized: {data.get('description', 'invalid token')}")
