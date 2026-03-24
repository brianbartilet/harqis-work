import os
import sys
import subprocess
from datetime import datetime, timedelta
from pathlib import Path

import psutil

from core.apps.sprout.app.celery import SPROUT
from core.apps.es_logging.app.elasticsearch import log_result
from core.utilities.logging.custom_logger import logger as log
from core.utilities.resources.decorators import get_decorator_attrs

from apps.apps_config import CONFIG_MANAGER
from apps.desktop.helpers.feed import feed
from apps.rainmeter.config import CONFIG as RAINMETER_CONFIG
from apps.antropic.config import CONFIG as ANTHROPIC_CONFIG
from apps.antropic.references.web.base_api_service import BaseApiServiceAnthropic

from workflows.prompts import load_prompt

_DAILY_SUMMARY_PROMPT = load_prompt('daily_summary')
_WEEKLY_SUMMARY_PROMPT = load_prompt('weekly_summary')

SCREENREADER_MARKER = "--desktop-screenreader"

# Windows flags
if os.name == "nt":
    HIDDEN_WINDOW = subprocess.CREATE_NO_WINDOW
    SHOW_WINDOW   = subprocess.CREATE_NEW_CONSOLE
else:
    HIDDEN_WINDOW = 0
    SHOW_WINDOW   = 0


def _kill_existing_screen_reader_processes():
    """
    Find and terminate any existing background screen reader processes.
    """
    for proc in psutil.process_iter(["pid", "name", "cmdline"]):
        try:
            name = (proc.info.get("name") or "").lower()
            cmdline = proc.info.get("cmdline") or []

            if name in ("python.exe", "pythonw.exe") and SCREENREADER_MARKER in cmdline:
                print(f"[screen reader] Killing old PID={proc.pid}")
                proc.terminate()
                try:
                    proc.wait(timeout=3)
                except psutil.TimeoutExpired:
                    proc.kill()
        except Exception:
            continue


@SPROUT.task(queue='default')
@log_result()
@feed()
def run_capture_logging(**kwargs):
    """
    Creates today's logfile and starts the run_capture loop
    either in a visible or hidden subprocess depending on config.
    """
    cfg = CONFIG_MANAGER.get(kwargs.get("cfg_id__desktop_utils", "DESKTOP"))

    base_path = cfg['capture'].get('actions_log_path',  os.getcwd())
    base_path = Path(base_path)
    base_path.mkdir(parents=True, exist_ok=True)
    console = cfg['capture'].get('show_console',  False)

    show_console = bool(cfg.get("show_console", console))

    _kill_existing_screen_reader_processes()

    creation_flag = SHOW_WINDOW if show_console else HIDDEN_WINDOW

    subprocess.Popen(
        [
            sys.executable,
            "-m",
            "core.utilities.capture.actions_entry",
            str(base_path),
            SCREENREADER_MARKER,
        ],
        creationflags=creation_flag,
    )

    return {
        "base_path": str(base_path),
        "visible_console": show_console,
        "status": "spawned",
    }


@SPROUT.task(queue='default')
@log_result()
def generate_daily_desktop_summary(hud_item_name='DESKTOP LOGS', logs_output_path='logs/daily', **kwargs):
    """
    Reads the get_desktop_logs dump.txt and sends it to Claude to produce
    a structured Markdown daily highlights file.

    Output: logs/daily/DESKTOP-LOGS-DD-MM-YYYY.md
    """
    try:
        anthropic = BaseApiServiceAnthropic(ANTHROPIC_CONFIG)
    except Exception as e:
        log.error("Failed to initialize Anthropic client for daily summary")
        raise e

    hud = hud_item_name.replace(" ", "").upper()
    dump_path = os.path.join(
        RAINMETER_CONFIG['write_skin_to_path'],
        RAINMETER_CONFIG['skin_name'],
        hud,
        "dump.txt",
    )

    if not os.path.exists(dump_path):
        log.warning(f"dump.txt not found at {dump_path} — skipping daily summary")
        return "SKIPPED: dump.txt not found"

    with open(dump_path, 'r', encoding='utf-8', errors='ignore') as f:
        dump_content = f.read()

    if not dump_content.strip():
        log.warning("dump.txt is empty — skipping daily summary")
        return "SKIPPED: dump.txt is empty"

    try:
        response = anthropic._with_backoff(
            anthropic.base_client.messages.create,
            model=anthropic.model,
            max_tokens=8192,
            messages=[{
                "role": "user",
                "content": f"{_DAILY_SUMMARY_PROMPT}\n\nActivity log dump:\n```\n{dump_content}\n```",
            }],
        )
        summary_md = response.content[0].text
    except Exception as e:
        log.error(f"Anthropic daily summary generation failed: {e}")
        return f"FAILED: {e}"

    today = datetime.now().strftime("%d-%m-%Y")
    output_dir = os.path.abspath(logs_output_path)
    os.makedirs(output_dir, exist_ok=True)
    output_file = os.path.join(output_dir, f"DESKTOP-LOGS-{today}.md")

    with open(output_file, 'w', encoding='utf-8') as f:
        f.write(summary_md)

    log.info(f"Daily summary written to {output_file}")
    return f"SUCCESS: {output_file}"


@SPROUT.task(queue='default')
@log_result()
def generate_weekly_desktop_summary(logs_daily_path='logs/daily', logs_output_path='logs/weekly', **kwargs):
    """
    Reads all daily DESKTOP-LOGS-*.md files from the past 7 days and sends them
    to Claude to produce a structured Markdown weekly highlights report.

    Output: logs/weekly/DESKTOP-LOGS-WEEK-WW-YYYY.md
    """
    try:
        anthropic = BaseApiServiceAnthropic(ANTHROPIC_CONFIG)
    except Exception as e:
        log.error("Failed to initialize Anthropic client for weekly summary")
        raise e

    today = datetime.now()
    week_num = today.strftime("%W")
    year = today.strftime("%Y")

    daily_dir = os.path.abspath(logs_daily_path)
    if not os.path.isdir(daily_dir):
        log.warning(f"Daily logs directory not found at {daily_dir} — skipping weekly summary")
        return "SKIPPED: daily logs directory not found"

    daily_files = []
    for i in range(7):
        day = today - timedelta(days=i)
        filename = f"DESKTOP-LOGS-{day.strftime('%d-%m-%Y')}.md"
        filepath = os.path.join(daily_dir, filename)
        if os.path.exists(filepath):
            daily_files.append((day, filepath))

    if not daily_files:
        log.warning("No daily summary files found for the past 7 days — skipping weekly summary")
        return "SKIPPED: no daily files found"

    daily_files.sort(key=lambda x: x[0])
    week_start = daily_files[0][0].strftime("%d %b")
    week_end = daily_files[-1][0].strftime("%d %b %Y")

    combined = []
    for day, filepath in daily_files:
        with open(filepath, 'r', encoding='utf-8', errors='ignore') as f:
            combined.append(f"<!-- {day.strftime('%A %d %b %Y')} -->\n{f.read()}")

    combined_content = "\n\n---\n\n".join(combined)
    prompt = (
        f"{_WEEKLY_SUMMARY_PROMPT}\n\n"
        f"Week number: {week_num}\n"
        f"Date range: {week_start} – {week_end}\n\n"
        f"Daily summaries:\n\n{combined_content}"
    )

    try:
        response = anthropic._with_backoff(
            anthropic.base_client.messages.create,
            model=anthropic.model,
            max_tokens=8192,
            messages=[{"role": "user", "content": prompt}],
        )
        summary_md = response.content[0].text
    except Exception as e:
        log.error(f"Anthropic weekly summary generation failed: {e}")
        return f"FAILED: {e}"

    output_dir = os.path.abspath(logs_output_path)
    os.makedirs(output_dir, exist_ok=True)
    output_file = os.path.join(output_dir, f"DESKTOP-LOGS-WEEK-{week_num}-{year}.md")

    with open(output_file, 'w', encoding='utf-8') as f:
        f.write(summary_md)

    log.info(f"Weekly summary written to {output_file}")
    return f"SUCCESS: {output_file}"
