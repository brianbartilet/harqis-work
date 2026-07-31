"""Bounded server-side OpenStreetMap Nominatim place search."""

from __future__ import annotations

import math
import threading
import time
from collections import OrderedDict

import httpx

from apps.openstreetmap import nominatim_rate_limit


_NOMINATIM_SEARCH_URL = "https://nominatim.openstreetmap.org/search"
_NOMINATIM_USER_AGENT = (
    "harqis-work-hfl/1.0 (personal location journal; "
    "+https://github.com/brianbartilet/harqis-work)"
)
_CACHE_TTL_SECONDS = 600.0
_CACHE_MAX_SIZE = 128
_CacheKey = tuple[str, int]
_CacheValue = tuple[tuple[str, str, str], ...]
_CACHE: OrderedDict[_CacheKey, tuple[float, _CacheValue]] = OrderedDict()
_CACHE_LOCK = threading.RLock()
_CACHE_TIMER: threading.Timer | None = None
_CACHE_GENERATION = 0


class LocationSearchError(RuntimeError):
    """Raised when an explicit place search cannot produce a safe response."""


def _coordinate(value: object, *, minimum: float, maximum: float) -> float | None:
    try:
        coordinate = float(str(value))
    except (TypeError, ValueError):
        return None
    if not math.isfinite(coordinate) or not minimum <= coordinate <= maximum:
        return None
    return coordinate


def _purge_expired_locked(now: float) -> None:
    for key, (expires_at, _) in tuple(_CACHE.items()):
        if expires_at <= now:
            _CACHE.pop(key, None)


def _schedule_expiry_locked() -> None:
    global _CACHE_GENERATION, _CACHE_TIMER
    _CACHE_GENERATION += 1
    if _CACHE_TIMER is not None:
        _CACHE_TIMER.cancel()
        _CACHE_TIMER = None
    if not _CACHE:
        return
    next_expiry = min(expires_at for expires_at, _ in _CACHE.values())
    delay = max(next_expiry - time.monotonic(), 0.0)
    timer = threading.Timer(delay, _expire_search_cache, args=(_CACHE_GENERATION,))
    timer.daemon = True
    timer.start()
    _CACHE_TIMER = timer


def _expire_search_cache(generation: int) -> None:
    global _CACHE_TIMER
    with _CACHE_LOCK:
        if generation != _CACHE_GENERATION:
            return
        _CACHE_TIMER = None
        _purge_expired_locked(time.monotonic())
        _schedule_expiry_locked()


def _clear_search_cache() -> None:
    global _CACHE_GENERATION, _CACHE_TIMER
    with _CACHE_LOCK:
        _CACHE.clear()
        _CACHE_GENERATION += 1
        if _CACHE_TIMER is not None:
            _CACHE_TIMER.cancel()
            _CACHE_TIMER = None


def _cache_get(key: _CacheKey) -> _CacheValue | None:
    with _CACHE_LOCK:
        now = time.monotonic()
        _purge_expired_locked(now)
        item = _CACHE.get(key)
        if item is None:
            _schedule_expiry_locked()
            return None
        expires_at, value = item
        if expires_at <= now:
            _CACHE.pop(key, None)
            _schedule_expiry_locked()
            return None
        _CACHE.move_to_end(key)
        _schedule_expiry_locked()
        return value


def _cache_put(key: _CacheKey, value: _CacheValue) -> None:
    with _CACHE_LOCK:
        now = time.monotonic()
        _purge_expired_locked(now)
        _CACHE[key] = (now + _CACHE_TTL_SECONDS, value)
        _CACHE.move_to_end(key)
        while len(_CACHE) > _CACHE_MAX_SIZE:
            _CACHE.popitem(last=False)
        _schedule_expiry_locked()


def _search_nominatim(
    normalized: str,
    bounded_limit: int,
) -> _CacheValue:
    try:
        nominatim_rate_limit()
        response = httpx.get(
            _NOMINATIM_SEARCH_URL,
            params={
                "q": normalized,
                "format": "jsonv2",
                "addressdetails": 1,
                "limit": bounded_limit,
            },
            headers={
                "User-Agent": _NOMINATIM_USER_AGENT,
                "Accept": "application/json",
            },
            timeout=10.0,
            follow_redirects=False,
        )
        response.raise_for_status()
        payload = response.json()
    except (httpx.HTTPError, OSError, ValueError) as exc:
        raise LocationSearchError(
            "Location search is unavailable right now. Enter coordinates manually or try again."
        ) from exc

    if not isinstance(payload, list):
        raise LocationSearchError(
            "Location search returned an invalid response. Enter coordinates manually."
        )

    results: list[tuple[str, str, str]] = []
    for item in payload[:bounded_limit]:
        if not isinstance(item, dict):
            continue
        latitude = _coordinate(item.get("lat"), minimum=-90, maximum=90)
        longitude = _coordinate(item.get("lon"), minimum=-180, maximum=180)
        label = " ".join(str(item.get("display_name") or "").split())[:300]
        if latitude is None or longitude is None or not label:
            continue
        results.append((label, f"{latitude:.5f}", f"{longitude:.5f}"))
    return tuple(results)


def search_nominatim(query: str, *, limit: int = 5) -> list[dict[str, str]]:
    """Search Nominatim after an explicit user submission, capped at five rows."""
    normalized = " ".join((query or "").split())
    if len(normalized) < 3:
        raise ValueError("Enter at least 3 characters to search for a location.")
    if len(normalized) > 200:
        raise ValueError("Location search must be 200 characters or fewer.")
    try:
        bounded_limit = min(max(int(limit), 1), 5)
    except (TypeError, ValueError) as exc:
        raise ValueError("Location result limit must be numeric.") from exc

    key = (normalized, bounded_limit)
    cached_results = _cache_get(key)
    if cached_results is None:
        cached_results = _search_nominatim(normalized, bounded_limit)
        _cache_put(key, cached_results)
    return [
        {"label": label, "latitude": latitude, "longitude": longitude}
        for label, latitude, longitude in cached_results
    ]
