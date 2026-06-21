import pytest


def skip_if_gemini_api_error(response: object) -> None:
    """Skip live Gemini smoke tests when configured credentials are missing/quota-limited."""
    data = getattr(response, "data", response)
    if not isinstance(data, dict):
        return
    error = data.get("error")
    if not isinstance(error, dict):
        return
    status = error.get("status")
    message = error.get("message", "Gemini API unavailable")
    if status in {"INVALID_ARGUMENT", "PERMISSION_DENIED", "RESOURCE_EXHAUSTED", "UNAUTHENTICATED"}:
        pytest.skip(f"Gemini API unavailable: {status}: {message}")
