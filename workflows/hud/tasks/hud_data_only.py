"""
Data-only fallback twins of the HUD render tasks.

Each twin runs on the always-on host (the `host` queue) and produces the
``@feed`` dump + ``@log_result`` Elasticsearch record ONLY when the Windows
worker hasn't run the original recently — the ``@fallback_gate`` reads the
original's `@log_result` heartbeat and short-circuits while Windows is healthy.
No Rainmeter render happens here.

This module is imported UNCONDITIONALLY from ``workflows/hud/__init__.py``
(outside the win32 guard), so it MUST stay win32-free: collectors + feed +
log_result + the fallback gate only — never ``apps.rainmeter`` / win32.

Generated/extended by the `/create-data-only-from-hud` skill.
"""
import logging

from core.apps.sprout.app.celery import SPROUT
from core.apps.es_logging.app.elasticsearch import log_result

from apps.desktop.helpers.feed import feed
from workflows.hud.fallback import fallback_gate
from workflows.hud.collectors.daily_radar import collect_daily_radar

logger = logging.getLogger("harqis-hud.data_only")


# ── DAILY RADAR ───────────────────────────────────────────────────────────────
# show_daily_radar fires crontab(hour='8,12,16,20'); the largest gap between
# consecutive fires is the 20:00→08:00 overnight window = 12h. Staleness =
# 12h + 10min grace, so the twin only engages when Windows has genuinely missed
# a scheduled run rather than during the legitimate overnight quiet period.
_STALENESS__DAILY_RADAR = 12 * 3600 + 600   # 43800s


@SPROUT.task(name="workflows.hud.tasks.hud_data_only.show_daily_radar_data_only")
@fallback_gate("workflows.hud.tasks.hud_radar.show_daily_radar", _STALENESS__DAILY_RADAR)
@log_result()
@feed(filename_prefix="hud-data-only")
def show_daily_radar_data_only(**kwargs):
    """Data-only fallback twin of show_daily_radar.

    Runs the same data collection + Claude synthesis as the Windows HUD task
    (minus the Rainmeter render and the Windows-local DESKTOP LOGS section) and
    writes the briefing to the `hud-data-only-YYYYMMDD.txt` feed + Elasticsearch
    — but only when the Windows worker hasn't rendered the radar within the
    staleness window. Pass `force=True` to bypass the gate for manual testing.
    """
    return collect_daily_radar(**kwargs)
