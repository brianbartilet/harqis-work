"""
Celery task dispatch and Flower-backed status tracking.

Dispatch uses a bare Celery app connected to the same broker as the workers —
no harqis-core imports required.

Status tracking uses Flower's REST API (/api/task/info/{id}).
If Flower is not reachable, the state is reported as UNKNOWN.
"""
import base64
import time
from functools import lru_cache
from typing import Any

import httpx
from celery import Celery

from config import get_settings

settings = get_settings()

# ── Celery client (dispatch only — no result backend needed) ───────────────────
@lru_cache(maxsize=1)
def _get_celery() -> Celery:
    app = Celery(broker=settings.celery_broker)
    app.conf.broker_connection_timeout = 5       # seconds before giving up
    app.conf.broker_connection_retry = False     # fail fast, don't retry
    app.conf.broker_connection_retry_on_startup = False
    return app


def dispatch(task_path: str, kwargs: dict, queue: str) -> str:
    """Send a task to the broker. Returns the Celery task UUID."""
    result = _get_celery().send_task(task_path, kwargs=kwargs, queue=queue)
    return result.id


# ── Flower status tracking ─────────────────────────────────────────────────────
_TERMINAL_STATES = {"SUCCESS", "FAILURE", "REVOKED"}


async def get_task_info(task_id: str) -> dict[str, Any]:
    """
    Query Flower for task status.
    Returns a normalized dict always containing at least {"state": <str>}.
    """
    if not settings.flower_url:
        return {"state": "UNKNOWN", "note": "FLOWER_URL not configured"}

    url = f"{settings.flower_url.rstrip('/')}/api/task/info/{task_id}"
    if settings.flower_user:
        creds = base64.b64encode(
            f"{settings.flower_user}:{settings.flower_password}".encode()
        ).decode()
        headers = {"Authorization": f"Basic {creds}"}
    else:
        headers = {}
    try:
        async with httpx.AsyncClient(timeout=5.0, follow_redirects=True) as client:
            resp = await client.get(url, headers=headers)
    except httpx.ConnectError:
        return {"state": "UNKNOWN", "note": "Flower unreachable"}
    except Exception as exc:
        return {"state": "UNKNOWN", "note": str(exc)}

    if resp.status_code == 404:
        # Task not yet received by Flower's event stream
        return {"state": "PENDING", "note": "Waiting for worker…"}
    if resp.status_code != 200:
        return {"state": "UNKNOWN", "note": f"Flower HTTP {resp.status_code}"}

    data: dict = resp.json()

    # Compute elapsed time for running tasks
    started = data.get("started")
    succeeded = data.get("succeeded")
    failed = data.get("failed")
    if started:
        end = succeeded or failed or time.time()
        data["elapsed"] = round(end - started, 2)

    # Truncate very long results/tracebacks for display
    if data.get("result") and len(str(data["result"])) > 2000:
        data["result"] = str(data["result"])[:2000] + "\n… [truncated]"
    if data.get("traceback") and len(str(data["traceback"])) > 3000:
        data["traceback"] = str(data["traceback"])[:3000] + "\n… [truncated]"

    return data


def is_terminal(state: str) -> bool:
    return state in _TERMINAL_STATES
