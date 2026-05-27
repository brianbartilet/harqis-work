"""Win32-free data collector for show_daily_radar (see /create-data-only-from-hud).

Lifts the DAILY RADAR data path — source collection, Claude synthesis, dump
composition, and summary/metrics — out of ``workflows/hud/tasks/hud_radar.py`` so
it can run on the always-on host with no Rainmeter/win32 dependency.

Both the Windows render task (``show_daily_radar``) and the host fallback twin
(``show_daily_radar_data_only``) call :func:`collect_daily_radar`. The only
Windows-specific input is the DESKTOP LOGS ``dump.txt`` tail; on the host that
path is simply absent, and ``collect_inputs`` reads an empty string for it
(``read_desktop_dump_tail`` returns "" when the file is missing) — so the host
twin produces the full briefing minus the desktop-context section.
"""
from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any, Dict, Optional

from core.utilities.logging.custom_logger import logger as log

from apps.antropic.config import get_config as get_anthropic_config
from apps.antropic.references.web.base_api_service import BaseApiServiceAnthropic

from workflows.hud.prompts import load_prompt
from workflows.hud.tasks.daily_radar_agent import (
    ANALYSIS_WINDOW_HOURS,
    DEFAULT_SOURCES,
    collect_inputs,
    format_inputs_as_prompt_text,
    summarise_inputs,
    wrap_preserving_breaks,
)

_DAILY_RADAR_PROMPT = load_prompt("daily_radar")


def collect_daily_radar(desktop_dump_path: Optional[str] = None, **kwargs) -> Dict[str, Any]:
    """Fetch + distill the DAILY RADAR briefing.

    Returns the same payload ``show_daily_radar`` returns, except the render-only
    ``links["dump"]`` (the Rainmeter skin dump path) and ``metrics["item_lines"]``
    are added by the Windows task after rendering — the host twin doesn't need them.

    Args:
        desktop_dump_path: Path to the DESKTOP LOGS dump.txt (input #1). Pass the
            resolved Rainmeter path on Windows; omit (None) on the host — the
            desktop section is then read as empty.
        **kwargs: ``sources``, ``source_overrides``, ``source_params``,
            ``cfg_id__anthropic``, ``model``, ``window_hours`` — same meaning as
            on ``show_daily_radar``. Render-only kwargs (e.g. ``max_hud_lines``)
            are accepted and ignored.
    """
    sources = kwargs.get("sources", DEFAULT_SOURCES)
    source_overrides = kwargs.get("source_overrides") or {}
    source_params = kwargs.get("source_params") or {}
    cfg_id__anthropic = kwargs.get("cfg_id__anthropic", "ANTHROPIC")
    model = kwargs.get("model", "claude-sonnet-4-6")
    window_hours = int(kwargs.get("window_hours", ANALYSIS_WINDOW_HOURS))

    # Every collector is wrapped in its own try/except inside collect_inputs, so
    # a single failing source (or an absent desktop dump on the host) never
    # breaks the briefing.
    payload = collect_inputs(
        sources=sources,
        desktop_dump_path=desktop_dump_path,
        hours=window_hours,
        source_overrides=source_overrides,
        source_params=source_params,
    )
    prompt_inputs = format_inputs_as_prompt_text(payload)

    briefing = _run_claude_synthesis(
        cfg_id__anthropic=cfg_id__anthropic,
        model=model,
        inputs_block=prompt_inputs,
    )

    # [START]/[END] mark the analysis window (now - window_hours → now), not the
    # run timestamp — the bookends convey the data range the briefing reflects.
    now = datetime.now()
    window_start = now - timedelta(hours=window_hours)
    fmt = "%Y-%m-%d %H:%M"
    body = wrap_preserving_breaks(briefing, width=65)
    dump = "\n[START] {0}\n\n{1}\n\n[END]   {2}\n\n".format(
        window_start.strftime(fmt), body, now.strftime(fmt),
    )

    metrics = summarise_inputs(payload)
    metrics["model"] = model

    # Build the summary from whatever sources actually ran.
    count_bits = []
    for name in metrics.get("sources_active") or []:
        key = "{0}_count".format(name)
        if key in metrics:
            count_bits.append("{0}={1}".format(name, metrics[key]))
    if metrics.get("has_location"):
        count_bits.append("loc=1")
    errored = metrics.get("sources_errored") or []
    err_bit = " err=[{0}]".format(",".join(errored)) if errored else ""

    return {
        "text": dump,
        "summary": "daily radar · window {0}h · {1}{2} · {3}".format(
            window_hours, " ".join(count_bits), err_bit, model,
        ),
        "metrics": metrics,
        "links": {"desktop_logs_dump": desktop_dump_path},
    }


def _run_claude_synthesis(cfg_id__anthropic: str,
                          model: str,
                          inputs_block: str) -> str:
    """Send the assembled inputs to Claude and return the briefing text.

    Falls back to a printable error string if the API call fails — the feed/HUD
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
        # send_message() (not the raw client) so the built-in Max -> API
        # fallback engages: a Claude Code OAuth-token rate-limit/quota hit is
        # caught as APIStatusError and retried against ANTHROPIC_API_KEY.
        response = anthropic.send_message(
            prompt=user_text,
            model=model,
            max_tokens=4096,
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
