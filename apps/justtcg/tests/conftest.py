"""Shared fixtures for the JustTCG live integration tests.

JustTCG's Free Tier allows only **10 requests/minute** (1,000/month, 100/day).
Live tests that fire several calls back-to-back trip HTTP 429 and would fail
non-deterministically, so every API call goes through :func:`invoke`, which:

  * paces calls to stay under the per-minute limit
    (override the spacing with ``JUSTTCG_TEST_MIN_INTERVAL`` on paid tiers),
  * retries on 429 with exponential backoff, honouring any ``Retry-After`` header
    (per https://justtcg.com/docs/rate-limits), and
  * **skips** (never fails) the test if the limit can't be cleared — a 429 is a
    quota/environment condition, not a code defect.
"""
import os
import threading
import time

import pytest

from core.web.services.core.response import Response
from apps.justtcg.config import CONFIG
from apps.justtcg.references.web.api.cards import ApiServiceJusttcgCards

# Free Tier = 10 req/min → ~1 call / 6s. 6.5s keeps a safety margin.
_MIN_INTERVAL = float(os.environ.get("JUSTTCG_TEST_MIN_INTERVAL", "6.5"))
_MAX_RETRIES = 5

_lock = threading.Lock()
_last_call = [0.0]


def _pace() -> None:
    """Block until at least ``_MIN_INTERVAL`` has elapsed since the last call."""
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
    """Call a JustTCG service method with free-tier pacing + 429 backoff.

    On success the deserialized result (list / DTO) is returned. On a sustained
    429 the test is skipped rather than failed.
    """
    delay = 1.0
    for attempt in range(_MAX_RETRIES):
        _pace()
        result = fn(*args, **kwargs)
        if _status_code(result) != 429:
            return result
        retry_after = None
        try:
            retry_after = result.headers.get("Retry-After")
        except Exception:
            pass
        time.sleep(float(retry_after) if retry_after else min(delay, 30.0))
        delay *= 2
    pytest.skip("JustTCG Free Tier rate limit (429) persisted after retries")


@pytest.fixture()
def call():
    """Function fixture: ``call(service.method, *args, **kwargs)`` — see :func:`invoke`."""
    return invoke


@pytest.fixture(scope="session")
def sample_cards():
    """One small set of real cards, fetched once and shared across card tests
    to minimise live-call volume against the free-tier quota."""
    service = ApiServiceJusttcgCards(CONFIG)
    result = invoke(service.search_cards, game="pokemon", limit=2)
    if not isinstance(result, list) or not result:
        pytest.skip("No sample cards available from JustTCG (rate-limited or empty)")
    return result
