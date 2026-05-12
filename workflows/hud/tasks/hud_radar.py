"""
DAILY RADAR HUD widget — every-4-hours productivity briefing.

Combines five agent ideas (#1, #3, #4, #12, #17 from data/AGENTS_IDEAS.md)
into a single Rainmeter widget:

  - Desktop context for the last 8 hours (tail of DESKTOP LOGS dump.txt).
  - Overlooked commitments scanned from email + desktop log.
  - Email priority for the last 8 hours.
  - Notification triage: failed Celery jobs + stuck Trello cards.
  - Morning-briefing-style top 3 priorities + suggested first move.

Width matches DESKTOP LOGS (`width_multiplier=2.25`) so the two pinned
widgets line up side by side. Height is FIXED at
`DAILY_RADAR_MAX_HUD_LINES` (30) — enough vertical space to see ~5 of the
radar's 7 content sections at once. Tighter defaults (15 like MOUSE
BINDINGS, 22 from the earlier attempt) hid too much of the briefing
behind the marquee. The marquee (`MeasureLuaScriptScroll`) still scrolls
content past the 30-line window so longer briefings don't grow the widget.

Two skin variables size the widget — they MUST stay in sync:

  * `ItemLines` — drives the meter/background height (the visible panel size).
  * `MaxLines`  — read by `TextCycle.lua` (the marquee script). Controls how
                  many lines render at once. Defaults to 16 in the Lua
                  script, so without setting it the marquee window stays
                  capped at 16 even when `ItemLines` grows the background.

Earlier iterations only set `ItemLines`, which made `max_hud_lines` look
like it only inflated the empty background. Both are now set together.
The widget surfaces on both WORK and ORGANIZE calendar blocks via
schedule_categories=[WORK, ORGANIZE]. play_sound=True triggers Rainmeter's
beep on each update.

Model: claude-sonnet-4-6 — text-only inputs at every-4-hours cadence;
Sonnet's stronger synthesis (over Haiku) produces a noticeably more
useful briefing for a once-per-shift widget. Pinned in the beat schedule
entry (workflows/hud/tasks_config.py::run-job--show_daily_radar) so the
model is explicit and obvious to anyone editing the schedule.
"""

import os
from datetime import datetime, timedelta

from core.apps.sprout.app.celery import SPROUT
from core.apps.es_logging.app.elasticsearch import log_result
from core.utilities.logging.custom_logger import logger as log
from core.utilities.resources.decorators import get_decorator_attrs

from apps.rainmeter.references.helpers.config_builder import (
    ConfigHelperRainmeter,
    init_meter,
)
from apps.rainmeter.config import CONFIG as RAINMETER_CONFIG
from apps.desktop.helpers.feed import feed

from apps.google_apps.references.constants import ScheduleCategory
from apps.google_apps.config import APP_NAME as APP_NAME_GOOGLE_APPS
from apps.trello.config import APP_NAME as APP_NAME_TRELLO
from apps.jira.config import APP_NAME as APP_NAME_JIRA

from apps.antropic.config import get_config as get_anthropic_config
from apps.antropic.references.web.base_api_service import BaseApiServiceAnthropic

from workflows.hud.prompts import load_prompt
# Fixed visible height. Matches JIRA BOARD's 14-line cap so the two
# work-block widgets sit at the same vertical footprint. The marquee
# scrolls everything past the visible window so longer briefings don't
# grow the widget. Override via the `max_hud_lines` kwarg if a different
# monitor wants more or less.
DAILY_RADAR_MAX_HUD_LINES: int = 16
from workflows.hud.tasks.sections import sections__daily_radar
from workflows.hud.tasks.daily_radar_agent import (
    ANALYSIS_WINDOW_HOURS,
    collect_inputs,
    format_inputs_as_prompt_text,
    summarise_inputs,
    wrap_preserving_breaks,
)


_DAILY_RADAR_PROMPT = load_prompt("daily_radar")

# DESKTOP LOGS skin folder — we need its dump.txt as one of our inputs.
# The folder name is the sanitized hud_item_name from hud_gpt.get_desktop_logs.
_DESKTOP_LOGS_HUD_FOLDER = "DESKTOPLOGS"


@SPROUT.task()
@log_result()
@init_meter(
    RAINMETER_CONFIG,
    hud_item_name="DAILY RADAR",
    new_sections_dict=sections__daily_radar,
    play_sound=True,
    schedule_categories=[ScheduleCategory.WORK, ScheduleCategory.ORGANIZE],
    # Overwrite dump.txt on every tick — the radar is a fresh briefing per
    # run, not a rolling log like DESKTOP LOGS. Older briefings would push
    # the current one off-screen and make the marquee scroll backwards
    # through stale content.
    prepend_if_exists=False,
)
@feed()
def show_daily_radar(ini=ConfigHelperRainmeter(), **kwargs):
    """Render the DAILY RADAR briefing.

    Each Google product has its own config key because each one carries a
    DIFFERENT OAuth scope and DIFFERENT storage file. The earlier single
    `cfg_id__gsuite="GOOGLE_APPS"` was wired to a calendar-only token,
    which made Gmail and Tasks return 403 `insufficientPermissions`.

    Kwargs:
        cfg_id__calendar:  Google Calendar config. Default 'GOOGLE_APPS'
                            (calendar.readonly scope, storage.json).
        cfg_id__gmail:     Gmail config. Default 'GOOGLE_GMAIL'
                            (gmail.readonly scope, storage-gmail.json).
        cfg_id__gtasks:    Google Tasks config. Default 'GOOGLE_TASKS'
                            (tasks scope, storage-tasks.json).
        cfg_id__trello:    Config key for Trello. Default 'TRELLO'.
        cfg_id__jira:      Config key for Jira (recent-update collector).
                            Default 'JIRA'.
        cfg_id__github:    Config key for GitHub PR sweep. Default 'GITHUB'.
                            Pulls open PRs where the user is author /
                            assignee / mentioned / review-requested,
                            updated in the analysis window.
        cfg_id__owntracks: Config key for OwnTracks last-location lookup.
                            Default 'OWN_TRACKS'. Pure context (home vs
                            office) used by the prompt to tailor suggestions.
        owntracks_user:    Optional OwnTracks username filter; defaults to
                            None (most recent device across the account).
        owntracks_device:  Optional OwnTracks device filter; requires user.
        cfg_id__anthropic: Config key for Anthropic. Default 'ANTHROPIC'.
        model:             Anthropic model id. Default Sonnet 4.6 —
                            stronger synthesis than Haiku for a once-per-
                            shift briefing; the beat schedule pins this
                            explicitly so the model choice is obvious.
        window_hours:      Analysis window in hours. Default 8.
        max_hud_lines:     Fixed visible HUD height. Default
                            `DAILY_RADAR_MAX_HUD_LINES` (14, matches JIRA
                            BOARD). Content beyond this scrolls via the
                            auto-scrolling marquee. Override to give the
                            radar more or less vertical space.
    """
    log.info("show_daily_radar kwargs: %s", list(kwargs.keys()))

    cfg_id__calendar = kwargs.get("cfg_id__calendar", APP_NAME_GOOGLE_APPS)
    cfg_id__gmail = kwargs.get("cfg_id__gmail", "GOOGLE_GMAIL")
    cfg_id__gtasks = kwargs.get("cfg_id__gtasks", "GOOGLE_TASKS")
    cfg_id__trello = kwargs.get("cfg_id__trello", APP_NAME_TRELLO)
    cfg_id__jira = kwargs.get("cfg_id__jira", APP_NAME_JIRA)
    cfg_id__github = kwargs.get("cfg_id__github", "GITHUB")
    cfg_id__owntracks = kwargs.get("cfg_id__owntracks", "OWN_TRACKS")
    cfg_id__anthropic = kwargs.get("cfg_id__anthropic", "ANTHROPIC")
    owntracks_user = kwargs.get("owntracks_user")
    owntracks_device = kwargs.get("owntracks_device")
    model = kwargs.get("model", "claude-sonnet-4-6")
    window_hours = int(kwargs.get("window_hours", ANALYSIS_WINDOW_HOURS))
    max_hud_lines_cap = int(kwargs.get("max_hud_lines", DAILY_RADAR_MAX_HUD_LINES))

    # region Compute the DESKTOP LOGS dump.txt path (input #1 — idea #1).
    # Matches the path get_desktop_logs writes to via @init_meter so the
    # radar always reads the freshest desktop analysis on disk.
    desktop_dump_path = os.path.join(
        RAINMETER_CONFIG["write_skin_to_path"],
        RAINMETER_CONFIG["skin_name"],
        _DESKTOP_LOGS_HUD_FOLDER,
        "dump.txt",
    )
    # endregion

    # region Header link — only the default `meterLink` slot (the user
    # explicitly asked for "only one link for the DUMP text").
    meta = get_decorator_attrs(show_daily_radar, prefix="")
    hud_folder = str(meta["_hud_item_name"]).replace(" ", "").upper()
    own_dump_path = os.path.join(
        RAINMETER_CONFIG["write_skin_to_path"],
        RAINMETER_CONFIG["skin_name"],
        hud_folder,
        "dump.txt",
    )

    ini["meterLink"]["text"] = "DUMP"
    ini["meterLink"]["leftmouseupaction"] = '!Execute ["{0}"]'.format(own_dump_path)
    ini["meterLink"]["tooltiptext"] = own_dump_path
    ini["meterLink"]["W"] = "80"
    # endregion

    # region Gather inputs — every collector is wrapped in its own try/except
    # inside daily_radar_agent.collect_inputs, so a single failing source
    # (e.g. Trello creds missing) never breaks the render.
    payload = collect_inputs(
        cfg_id__calendar=cfg_id__calendar,
        cfg_id__gmail=cfg_id__gmail,
        cfg_id__gtasks=cfg_id__gtasks,
        cfg_id__trello=cfg_id__trello,
        cfg_id__jira=cfg_id__jira,
        cfg_id__github=cfg_id__github,
        cfg_id__owntracks=cfg_id__owntracks,
        desktop_dump_path=desktop_dump_path,
        hours=window_hours,
        owntracks_user=owntracks_user,
        owntracks_device=owntracks_device,
    )
    prompt_inputs = format_inputs_as_prompt_text(payload)
    # endregion

    # region Send to Claude — Sonnet 4.6 is pinned by the beat schedule.
    briefing = _run_claude_synthesis(
        cfg_id__anthropic=cfg_id__anthropic,
        model=model,
        inputs_block=prompt_inputs,
    )
    # endregion

    # region Compose dump — preserve the prompt's section breaks (the old
    # core.utilities.data.strings.wrap_text joined everything with spaces
    # and collapsed the structure into a single paragraph). The helper
    # wraps each line independently and passes blank lines through so the
    # bulleted lists and `===` rules survive into the HUD.
    #
    # [START] / [END] mark the actual analysis window the radar covers
    # (now - window_hours → now), not the run timestamp. The user wanted
    # the bookends to convey the data range so they can see at a glance
    # what slice of the day the briefing reflects.
    now = datetime.now()
    window_start = now - timedelta(hours=window_hours)
    fmt = "%Y-%m-%d %H:%M"
    # Wrap width tuned to width_multiplier=2.25 (DESKTOP LOGS column width).
    body = wrap_preserving_breaks(briefing, width=65)
    dump = "\n[START] {0}\n\n{1}\n\n[END]   {2}\n\n".format(
        window_start.strftime(fmt),
        body,
        now.strftime(fmt),
    )
    # endregion

    # region Dimensions — width matches DESKTOP LOGS (2.25) so the two
    # pinned widgets line up side by side; height is FIXED like MOUSE
    # BINDINGS (no compute_max_hud_lines dynamic expansion). The marquee
    # scrolls everything past `max_hud_lines_cap` so the widget's footprint
    # stays predictable across runs regardless of briefing length.
    width_multiplier = 2.25
    max_hud_lines = max_hud_lines_cap  # fixed height, like MOUSE BINDINGS

    ini["meterSeperator"]["W"] = "({0}*186*#Scale#)".format(width_multiplier)

    ini["MeterDisplay"]["W"] = "({0}*186*#Scale#)".format(width_multiplier)
    ini["MeterDisplay"]["H"] = "((42*#Scale#)+(#ItemLines#*22)*#Scale#)"
    ini["MeterDisplay"]["X"] = "14"
    # MeasureLuaScriptScroll → auto-scroll marquee, same as DESKTOP LOGS.
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
    # endregion
    # `ItemLines` drives the meter background height (the visible panel
    # size). `MaxLines` is read by TextCycle.lua and controls how many
    # lines the marquee renders at once — defaulting to 16 inside the Lua
    # script. Without setting it explicitly, bumping `ItemLines` only
    # grows the empty background while the text window stays capped at 16.
    # Keep the two in sync so the marquee actually uses the panel we paint.
    ini["Variables"]["ItemLines"] = "{0}".format(max_hud_lines)
    ini["Variables"]["MaxLines"] = "{0}".format(max_hud_lines)

    metrics = summarise_inputs(payload)
    metrics["item_lines"] = max_hud_lines
    metrics["model"] = model

    return {
        "text": dump,
        "summary": (
            "daily radar · window {0}h · "
            "email={email_count} cal={calendar_count} "
            "tasks={task_count} trello={trello_count} "
            "jira={jira_count} gh={github_pr_count} loc={has_location} "
            "failed={failed_job_count} · {model}"
        ).format(window_hours, **metrics),
        "metrics": metrics,
        "links": {
            "dump": own_dump_path,
            "desktop_logs_dump": desktop_dump_path,
        },
    }


def _run_claude_synthesis(cfg_id__anthropic: str,
                         model: str,
                         inputs_block: str) -> str:
    """Send the assembled inputs to Claude and return the briefing text.

    Falls back to a printable error string if the API call fails — the HUD
    keeps rendering even when the network or quota is down.
    """
    try:
        anthropic = BaseApiServiceAnthropic(get_anthropic_config(cfg_id__anthropic))
    except Exception as e:
        log.error("DAILY RADAR: anthropic init failed: %s", e)
        return "DAILY RADAR offline — anthropic init failed: {0}".format(e)

    user_text = "{prompt}\n\n{inputs}".format(
        prompt=_DAILY_RADAR_PROMPT,
        inputs=inputs_block,
    )

    try:
        response = anthropic._with_backoff(
            anthropic.base_client.messages.create,
            model=model,
            max_tokens=4096,
            messages=[{"role": "user", "content": user_text}],
        )
        return response.content[0].text
    except Exception as e:
        cause = e.__cause__ or e.__context__
        log.error(
            "DAILY RADAR: anthropic call failed [%s]: %s%s",
            type(e).__name__, e,
            " | caused by [{0}]: {1}".format(type(cause).__name__, cause) if cause else "",
        )
        return "DAILY RADAR offline — anthropic call failed [{0}]: {1}".format(
            type(e).__name__, e,
        )
