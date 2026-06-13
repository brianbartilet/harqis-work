"""Shared fixtures for the Pokemon TCG API live integration tests.

api.pokemontcg.io is keyless-limited to 30 requests/minute and has patchy
uptime (~71% over 30 days per public monitors), so every live call goes
through :func:`invoke`, which paces requests, retries 429/5xx with backoff,
and **skips** (never fails) when the service can't be reached — an outage is
an environment condition, not a code defect.
"""
import os
import threading
import time

import pytest

from core.web.services.core.response import Response

# Keyless tier = 30 req/min → 1 call / 2s. 2.2s keeps a safety margin.
_MIN_INTERVAL = float(os.environ.get("POKEMON_TCG_TEST_MIN_INTERVAL", "2.2"))
_MAX_RETRIES = 4

_lock = threading.Lock()
_last_call = [0.0]


def _pace() -> None:
    with _lock:
        wait = _MIN_INTERVAL - (time.monotonic() - _last_call[0])
        if wait > 0:
            time.sleep(wait)
        _last_call[0] = time.monotonic()


def _status_code(result):
    """Return the HTTP status if ``result`` is a raw (un-deserialized) Response."""
    if not isinstance(result, Response):
        return None
    try:
        return int(result.status_code)
    except Exception:
        return None


def invoke(fn, *args, **kwargs):
    """Call a Pokemon TCG service method with pacing + 429/5xx backoff.

    On success the deserialized result (list / DTO) is returned. On a
    sustained failure or connection error the test is skipped.
    """
    delay = 2.0
    for attempt in range(_MAX_RETRIES):
        _pace()
        try:
            result = fn(*args, **kwargs)
        except Exception as e:
            if attempt == _MAX_RETRIES - 1:
                pytest.skip(f"api.pokemontcg.io unreachable: {e}")
            time.sleep(delay)
            delay *= 2
            continue
        status = _status_code(result)
        if status is None or status < 429:
            return result
        time.sleep(delay)
        delay *= 2
    pytest.skip("api.pokemontcg.io rate limit / outage persisted after retries")


@pytest.fixture()
def call():
    """Function fixture: ``call(service.method, *args, **kwargs)`` — see :func:`invoke`."""
    return invoke
