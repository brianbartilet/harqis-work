"""Rainmeter presentation adapter for the canonical Second Brain feed."""

from __future__ import annotations

from core.apps.es_logging.app.elasticsearch import log_result
from core.apps.sprout.app.celery import SPROUT

from apps.desktop.helpers.feed import feed
from apps.google_apps.references.constants import ScheduleCategory
from apps.rainmeter.config import CONFIG as RAINMETER_CONFIG
from apps.rainmeter.references.helpers.config_builder import ConfigHelperRainmeter, init_meter
from workflows.second_brain.adapters import client_items, render_text
from workflows.second_brain.store import get_store


@SPROUT.task()
@log_result()
@init_meter(
    RAINMETER_CONFIG,
    hud_item_name="SECOND BRAIN",
    new_sections_dict={},
    play_sound=False,
    schedule_categories=[ScheduleCategory.PINNED],
    prepend_if_exists=False,
)
@feed(filename_prefix="second-brain")
def render_second_brain_rainmeter(ini=ConfigHelperRainmeter(), **_kwargs):
    """Render the latest redacted canonical snapshot on the Windows HUD."""
    store = get_store()
    config = store.get_config()
    if not (config.get("clients") or {}).get("rainmeter", False):
        return {"text": "SECOND BRAIN\n\nRainmeter delivery is disabled."}
    decision = store.latest_decision() or {}
    items = client_items(
        store.feed_snapshot(
            client="rainmeter",
            limit=12,
            modes=decision.get("effective_modes") or (),
        ),
        client="rainmeter",
    )
    text = render_text(items, limit=12)
    ini["Variables"]["ItemLines"] = str(max(6, min(18, len(text.splitlines()) + 1)))
    ini["MeterDisplay"]["W"] = "(3*190*#Scale#)"
    ini["Rainmeter"]["SkinWidth"] = "(3*198*#Scale#)"
    ini["meterTitle"]["W"] = "(3*190*#Scale#)"
    ini["meterTitle"]["X"] = "(3*190*#Scale#)/2"
    return {"text": text, "summary": f"{len(items)} advisory item(s)"}
