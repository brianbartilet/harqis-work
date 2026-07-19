"""Host-side exporter for the sanitized scheduled Telegram mirror."""

from core.apps.sprout.app.celery import SPROUT
from core.utilities.logging.custom_logger import logger as log

from workflows.hud.collectors.hermes_pushes import (
    DEFAULT_MAX_ITEMS,
    DEFAULT_WINDOW_HOURS,
    export_snapshot,
    resolve_snapshot_path,
)


@SPROUT.task()
def export_hermes_radar_snapshot(**kwargs):
    """Refresh the shared JSON artifact without calling an LLM or Telegram."""
    snapshot = export_snapshot(
        snapshot_path=kwargs.get("snapshot_path"),
        hermes_home=kwargs.get("hermes_home"),
        window_hours=int(kwargs.get("window_hours", DEFAULT_WINDOW_HOURS)),
        max_items=int(kwargs.get("max_items", DEFAULT_MAX_ITEMS)),
    )
    destination = resolve_snapshot_path(kwargs.get("snapshot_path"))
    log.info(
        "export_hermes_radar_snapshot: wrote %s scheduled deliveries to %s",
        len(snapshot["items"]),
        destination.name,
    )
    return {
        "summary": f"Exported {len(snapshot['items'])} scheduled Hermes deliveries",
        "metrics": {"items": len(snapshot["items"])},
        "artifact": destination.name,
    }
