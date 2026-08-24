"""Best-effort Redis Stream notifications backed by canonical SQLite state."""

from __future__ import annotations

import json
import os
from typing import Any


STREAM_KEY = "second-brain:feed:v1"


def publish_feed_change(payload: dict[str, Any]) -> str:
    """Publish a bounded notification; canonical persistence has already happened."""
    redis_url = os.environ.get("SECOND_BRAIN_REDIS_URL", os.environ.get("REDIS_URL", "")).strip()
    if not redis_url:
        return "disabled"
    try:
        import redis

        client = redis.Redis.from_url(redis_url, decode_responses=True, socket_timeout=2)
        return str(
            client.xadd(
                STREAM_KEY,
                {"revision": str(payload.get("revision", 0)), "item": json.dumps(payload, default=str)},
                maxlen=5_000,
                approximate=True,
            )
        )
    except Exception:
        return "unavailable"
