"""
Demo broadcast task — fans out to every HUD worker that subscribes to the
`hud_broadcast` fanout queue.

The naming convention `broadcast_*` is what the routing rule in
`workflows/config.py` keys on:

    "workflows.hud.tasks.broadcast_*": {"queue": "hud_broadcast"}

Any task in `workflows/hud/tasks/` whose function name starts with `broadcast_`
is automatically routed to the fanout queue. To trigger a fan-out:

    from workflows.hud.tasks.broadcast_reload import broadcast_reload_config
    broadcast_reload_config.delay()
    # → every HUD worker subscribed to `hud_broadcast` runs the task once.

**Idempotency rule.** Broadcast tasks run on every subscribed worker
simultaneously. Make sure the body is safe under concurrent execution on
multiple machines: no shared file writes, no shared external state without
locking, no operations that should "happen exactly once cluster-wide" (use a
direct queue for those).

Subscription:
    Workers subscribe by including `hud_broadcast` in their `-Q` queue list.
    `deploy.sh --with-broadcast` auto-appends it for HUD workers.
"""

import logging
import platform
import socket
from datetime import datetime, timezone

from core.apps.sprout.app.celery import SPROUT


logger = logging.getLogger(__name__)


@SPROUT.task(name="workflows.hud.tasks.broadcast_reload_config")
def broadcast_reload_config(**kwargs) -> dict:
    """Cluster-wide reload of HUD-side configuration on every subscribed worker.

    This is intentionally lightweight — it just records that the worker received
    the broadcast and (in real use) would re-read its local Rainmeter / desktop
    configuration. The pattern is reusable: any "tell every HUD machine to
    refresh state from disk" workflow plugs in here.

    Returns a small status dict so Flower / Elasticsearch logs show which worker
    handled which fan-out.
    """
    hostname = socket.gethostname()
    payload = {
        "task": "broadcast_reload_config",
        "host": hostname,
        "platform": platform.system().lower(),
        "received_at": datetime.now(timezone.utc).isoformat(),
        "kwargs": kwargs,
    }
    logger.info("[hud_broadcast] reload_config received on %s — payload=%s", hostname, payload)
    return payload
