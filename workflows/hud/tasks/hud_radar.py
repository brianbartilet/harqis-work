"""HERMES RADAR HUD — 12-hour mirror of scheduled Telegram deliveries.

The established DAILYRADAR Rainmeter folder and task names remain unchanged for
compatibility. The visible panel title is HERMES RADAR. A lightweight refresh
runs hourly from a sanitized shared JSON snapshot. The existing
multi-source Claude synthesis still runs at 08:00, 12:00, 16:00, and 20:00 for
feed/HFL consumers, but it is no longer appended to the visible dump.
"""

import os

from core.apps.sprout.app.celery import SPROUT
from core.apps.es_logging.app.elasticsearch import log_result
from core.utilities.logging.custom_logger import logger as log

from apps.rainmeter.references.helpers.config_builder import (
    ConfigHelperRainmeter,
    init_meter,
)
from apps.rainmeter.config import CONFIG as RAINMETER_CONFIG
from apps.desktop.helpers.feed import feed
from apps.google_apps.references.constants import ScheduleCategory

from workflows.hud.tasks.sections import sections__daily_radar
from workflows.hud.collectors.daily_radar import collect_daily_radar
from workflows.hud.collectors.hermes_pushes import (
    compose_hermes_radar,
    displayed_item_count,
    load_snapshot,
)

DAILY_RADAR_MAX_HUD_LINES: int = 19
DAILY_RADAR_WRAP_AT: int = 56
_DESKTOP_LOGS_HUD_FOLDER = "DESKTOPLOGS"
# Compatibility path used by forwarding scripts and existing Rainmeter installs.
_RADAR_HUD_FOLDER = "DAILYRADAR"


def _radar_dump_path() -> str:
    return os.path.join(
        RAINMETER_CONFIG["write_skin_to_path"],
        RAINMETER_CONFIG["skin_name"],
        _RADAR_HUD_FOLDER,
        "dump.txt",
    )


def _configure_radar_ini(
    ini: ConfigHelperRainmeter, *, dump_path: str, max_hud_lines: int
) -> None:
    """Apply the shared HERMES RADAR link, dimensions, and marquee settings."""
    ini["meterLink"]["text"] = "DUMP"
    ini["meterLink"]["leftmouseupaction"] = '!Execute ["{0}"]'.format(dump_path)
    ini["meterLink"]["tooltiptext"] = dump_path
    ini["meterLink"]["W"] = "80"

    width_multiplier = 2.25
    ini["meterSeperator"]["W"] = "({0}*186*#Scale#)".format(width_multiplier)
    # Increase the left inset by 8 px while removing the same amount from the
    # content width, preserving the established right margin.
    ini["MeterDisplay"]["W"] = "(({0}*186-8)*#Scale#)".format(width_multiplier)
    # The content meter begins 70 px below the top of the skin. Its height
    # must therefore be the remaining viewport, not the full SkinHeight;
    # otherwise wrapped text paints over the HUD below during initial load.
    # SkinHeight = (42 + ItemLines*22), so subtract Y=70 and a 14 px footer:
    # (42 + ItemLines*22) - 70 - 14 = ItemLines*22 - 42.
    ini["MeterDisplay"]["H"] = "((#ItemLines#*22-42)*#Scale#)"
    ini["MeterDisplay"]["X"] = "(22*#Scale#)"
    ini["MeterDisplay"]["Y"] = "(70*#Scale#)"
    ini["MeterDisplay"]["MeasureName"] = "MeasureLuaScriptScroll"
    ini["MeterBackground"]["Shape"] = (
        "Rectangle 0,0,({0}*190),((#ItemLines#*22)),2 | Fill Color #fillColor# "
        "| StrokeWidth (1*#Scale#) | Stroke Color [#darkColor] "
        "| Scale #Scale#,#Scale#,0,0"
    ).format(width_multiplier)
    ini["MeterBackgroundTop"]["Shape"] = (
        "Rectangle 3,3,({0}*186),25,2 | Fill Color #headerColor# | StrokeWidth 0 "
        "| Stroke Color [#darkColor] | Scale #Scale#,#Scale#,0,0"
    ).format(width_multiplier)
    ini["Rainmeter"]["SkinWidth"] = "({0}*198*#Scale#)".format(width_multiplier)
    ini["Rainmeter"]["SkinHeight"] = "((42*#Scale#)+(#ItemLines#*22)*#Scale#)"
    ini["meterTitle"]["W"] = "({0}*190*#Scale#)".format(width_multiplier)
    ini["meterTitle"]["X"] = "({0}*198*#Scale#)/2".format(width_multiplier)
    ini["Variables"]["ItemLines"] = str(max_hud_lines)
    ini["Variables"]["MaxLines"] = str(max_hud_lines)
    # TextCycle normally counts physical dump lines. Hermes summaries can
    # contain very long physical lines, which Rainmeter then wraps into several
    # visual rows after the marquee has already selected its window. Pre-wrap
    # this skin's input inside TextCycle so MaxLines remains a true display-row
    # cap and no scroll frame crowds or crosses the panel footer.
    ini["Variables"]["WrapAt"] = str(DAILY_RADAR_WRAP_AT)


@SPROUT.task()
@log_result()
@init_meter(
    RAINMETER_CONFIG,
    hud_item_name="HERMES RADAR",
    hud_folder_name="DAILY RADAR",
    new_sections_dict=sections__daily_radar,
    play_sound=True,
    schedule_categories=[ScheduleCategory.PINNED],
    prepend_if_exists=False,
)
@feed()
def show_daily_radar(ini=ConfigHelperRainmeter(), **kwargs):
    """Run the synthesis for feeds while rendering scheduled deliveries only."""
    log.info("show_daily_radar kwargs: %s", list(kwargs.keys()))
    max_hud_lines = int(kwargs.get("max_hud_lines", DAILY_RADAR_MAX_HUD_LINES))
    own_dump_path = _radar_dump_path()

    desktop_dump_path = os.path.join(
        RAINMETER_CONFIG["write_skin_to_path"],
        RAINMETER_CONFIG["skin_name"],
        _DESKTOP_LOGS_HUD_FOLDER,
        "dump.txt",
    )
    result = collect_daily_radar(desktop_dump_path=desktop_dump_path, **kwargs)
    briefing = result["text"]
    snapshot = load_snapshot(kwargs.get("snapshot_path"))
    # Preserve the established synthesis-only feed contract used by HFL and
    # the legacy Telegram forwarder. Scheduled deliveries stay in the HUD dump
    # and sanitized JSON snapshot only.
    result["feed_text"] = briefing
    result["text"] = compose_hermes_radar(snapshot)

    _configure_radar_ini(ini, dump_path=own_dump_path, max_hud_lines=max_hud_lines)
    result.setdefault("links", {})["dump"] = own_dump_path
    result.setdefault("metrics", {})["item_lines"] = max_hud_lines
    result["metrics"]["hermes_pushes"] = displayed_item_count(snapshot)
    return result


@SPROUT.task()
@init_meter(
    RAINMETER_CONFIG,
    hud_item_name="HERMES RADAR",
    hud_folder_name="DAILY RADAR",
    new_sections_dict=sections__daily_radar,
    play_sound=False,
    schedule_categories=[ScheduleCategory.PINNED],
    prepend_if_exists=False,
)
def refresh_hermes_radar(ini=ConfigHelperRainmeter(), **kwargs):
    """Rerender the 12-hour Telegram mirror without source pulls or an LLM."""
    max_hud_lines = int(kwargs.get("max_hud_lines", DAILY_RADAR_MAX_HUD_LINES))
    own_dump_path = _radar_dump_path()
    snapshot = load_snapshot(kwargs.get("snapshot_path"))
    text = compose_hermes_radar(snapshot)

    _configure_radar_ini(ini, dump_path=own_dump_path, max_hud_lines=max_hud_lines)
    return {
        "text": text,
        "summary": "Refreshed HERMES RADAR from the sanitized snapshot",
        "metrics": {
            "item_lines": max_hud_lines,
            "hermes_pushes": displayed_item_count(snapshot),
            "snapshot_state": snapshot.get("state", "unavailable"),
            "llm_calls": 0,
        },
        "links": {"dump": own_dump_path},
    }
