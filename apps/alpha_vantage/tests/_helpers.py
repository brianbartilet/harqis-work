import pytest


def skip_if_alpha_vantage_throttled(response: object) -> None:
    if not isinstance(response, dict):
        return
    message = response.get("Information") or response.get("Note")
    if isinstance(message, str) and ("rate limit" in message.lower() or "frequency" in message.lower()):
        pytest.skip(f"Alpha Vantage quota/rate limit: {message}")
