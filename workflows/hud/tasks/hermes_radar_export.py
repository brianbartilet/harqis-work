"""Host-side exporter for the sanitized HERMES RADAR Telegram snapshot."""

from core.apps.sprout.app.celery import SPROUT
from core.utilities.logging.custom_logger import logger as log

from workflows.hud.collectors.hermes_pushes import export_snapshot, resolve_snapshot_path


@SPROUT.task()
def export_hermes_radar_snapshot(**kwargs):
    """Refresh the shared JSON artifact without calling an LLM or Telegram."""
    snapshot = export_snapshot(
        snapshot_path=kwargs.get("snapshot_path"),
        hermes_home=kwargs.get("hermes_home"),
        window_hours=int(kwargs.get("window_hours", 8)),
        max_items=int(kwargs.get("max_items", 10)),
    )
    destination = resolve_snapshot_path(kwargs.get("snapshot_path"))
    log.info(
        "export_hermes_radar_snapshot: wrote %s sanitized pushes to %s",
        len(snapshot["items"]),
        destination.name,
    )
    return {
        "summary": f"Exported {len(snapshot['items'])} sanitized Hermes pushes",
        "metrics": {"items": len(snapshot["items"])},
        "artifact": destination.name,
    }
