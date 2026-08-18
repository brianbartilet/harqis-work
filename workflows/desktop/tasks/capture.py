import json
import os
import sys
import subprocess
import time
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
from apps.antropic.config import get_config as get_anthropic_config
from apps.antropic.references.web.base_api_service import BaseApiServiceAnthropic

from workflows.desktop.prompts import load_prompt

_DAILY_SUMMARY_PROMPT = load_prompt('daily_summary')
_WEEKLY_SUMMARY_PROMPT = load_prompt('weekly_summary')

SCREENREADER_MARKER = "--desktop-screenreader"
SCREENREADER_STATE_FILE = "actions_screenreader.json"
SCREENREADER_HEALTH_FILE = "actions_health.json"
DEFAULT_MAX_MEMORY_MB = 768

# Hard cap on raw dump content shipped to Claude. ~600KB ≈ 150k tokens at the
# typical 4-chars-per-token rate for mixed-English text — comfortably inside
# Haiku's 200k context (and Sonnet's 200k / 1M). Anything older is dropped;
# the prompt gets a marker line so the model knows it's seeing the tail.
MAX_DUMP_CHARS = 600_000


def _tail_with_marker(text: str, max_chars: int) -> str:
    """Return the last `max_chars` of `text`. If truncated, prepend a marker
    line so the LLM treats the slice as a tail and doesn't hallucinate the
    missing earlier context."""
    if len(text) <= max_chars:
        return text
    dropped = len(text) - max_chars
    return (
        f"[truncated: dropped {dropped:,} earlier chars; kept last {max_chars:,}]\n"
        + text[-max_chars:]
    )

# Windows flags
if os.name == "nt":
    HIDDEN_WINDOW = subprocess.CREATE_NO_WINDOW
    SHOW_WINDOW   = subprocess.CREATE_NEW_CONSOLE
else:
    HIDDEN_WINDOW = 0
    SHOW_WINDOW   = 0


def _matching_screen_reader_processes() -> list[psutil.Process]:
    """Return every live Python process belonging to the capture instance."""
    matches = []
    for proc in psutil.process_iter(["pid", "name", "cmdline"]):
        try:
            name = (proc.info.get("name") or "").lower()
            cmdline = proc.info.get("cmdline") or []
            if name in ("python.exe", "pythonw.exe") and SCREENREADER_MARKER in cmdline:
                matches.append(proc)
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue
    return matches


def _terminate_process_forest(processes: list[psutil.Process]) -> None:
    """Terminate complete capture process trees, children before parents."""
    by_pid = {proc.pid: proc for proc in processes}
    for proc in list(processes):
        try:
            for child in proc.children(recursive=True):
                by_pid[child.pid] = child
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            pass
    ordered = list(by_pid.values())
    for proc in reversed(ordered):
        try:
            proc.terminate()
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            pass
    _, alive = psutil.wait_procs(ordered, timeout=3)
    for proc in alive:
        try:
            proc.kill()
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            pass


def _capture_families(processes: list[psutil.Process]) -> list[psutil.Process]:
    """Return roots of marker-bearing process families (venv launchers included)."""
    pids = {proc.pid for proc in processes}
    roots = []
    for proc in processes:
        try:
            if proc.ppid() not in pids:
                roots.append(proc)
        except psutil.NoSuchProcess:
            continue
    return roots


def _write_screen_reader_state(base_path: Path, processes: list[psutil.Process]) -> Path:
    destination = base_path / SCREENREADER_STATE_FILE
    payload = {
        "updated_at": datetime.now().isoformat(),
        "pids": sorted(proc.pid for proc in processes if proc.is_running()),
        "marker": SCREENREADER_MARKER,
        "health_path": str(base_path / SCREENREADER_HEALTH_FILE),
    }
    temporary = destination.with_suffix(".tmp")
    temporary.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    os.replace(temporary, destination)
    return destination


def _read_capture_health(base_path: Path) -> dict:
    try:
        return json.loads((base_path / SCREENREADER_HEALTH_FILE).read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return {}


def _capture_health_is_fresh(
    health: dict,
    processes: list[psutil.Process],
    *,
    max_age_seconds: float = 120,
) -> bool:
    """Require recent telemetry from a PID in the discovered process family."""
    try:
        timestamp = datetime.fromisoformat(health["timestamp"])
        age = (datetime.now() - timestamp).total_seconds()
        live_pids = {proc.pid for proc in processes if proc.is_running()}
        return 0 <= age <= max_age_seconds and int(health["pid"]) in live_pids
    except (KeyError, TypeError, ValueError, OSError, psutil.Error):
        return False


@log_result()
@feed()
@SPROUT.task()
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

    existing = _matching_screen_reader_processes()
    families = _capture_families(existing)
    health = _read_capture_health(base_path)
    if len(families) == 1 and _capture_health_is_fresh(health, existing):
        state_path = _write_screen_reader_state(base_path, existing)
        return {
            "base_path": str(base_path),
            "visible_console": show_console,
            "status": "already_running",
            "pids": sorted(proc.pid for proc in existing),
            "state_path": str(state_path),
            "health": health,
        }
    if existing:
        log.warning(
            "Replacing unhealthy screen reader: families=%s processes=%s health_fresh=%s",
            len(families),
            len(existing),
            _capture_health_is_fresh(health, existing),
        )
        _terminate_process_forest(existing)

    creation_flag = SHOW_WINDOW if show_console else HIDDEN_WINDOW
    child_env = os.environ.copy()
    child_env["CAPTURE_MAX_MEMORY_MB"] = str(
        cfg["capture"].get("max_memory_mb", DEFAULT_MAX_MEMORY_MB)
    )
    child_env["CAPTURE_IDLE_PAUSE_SECONDS"] = str(
        cfg["capture"].get("idle_pause_seconds", 300)
    )
    child_env["CAPTURE_FOCUS_INTERVAL_SECONDS"] = str(
        cfg["capture"].get("focus_interval_seconds", 1.0)
    )

    process = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "core.utilities.capture.actions_entry",
            str(base_path),
            SCREENREADER_MARKER,
        ],
        creationflags=creation_flag,
        env=child_env,
    )
    # The Windows venv launcher may hand off to a base-interpreter child. Give
    # that handoff a moment, then record the whole family rather than a PID that
    # can immediately become stale.
    time.sleep(0.5)
    launched = _matching_screen_reader_processes()
    if not launched and process.poll() is None:
        launched = [psutil.Process(process.pid)]
    state_path = _write_screen_reader_state(base_path, launched)

    return {
        "base_path": str(base_path),
        "visible_console": show_console,
        "status": "spawned",
        "pids": sorted(proc.pid for proc in launched),
        "state_path": str(state_path),
        "health_path": str(base_path / SCREENREADER_HEALTH_FILE),
        "max_memory_mb": int(child_env["CAPTURE_MAX_MEMORY_MB"]),
    }


@log_result()
@SPROUT.task()
def generate_daily_desktop_summary(hud_item_name='DESKTOP LOGS', logs_output_path='logs/daily', **kwargs):
    """
    Reads the get_desktop_logs dump.txt and sends it to Claude to produce
    a structured Markdown daily highlights file.

    Kwargs:
        cfg_id__anthropic: Config key for the Anthropic client. Default 'ANTHROPIC'.
        model:             Optional model override. When omitted, falls
                           back to ``BaseApiServiceAnthropic``'s configured
                           model. The celery schedule passes
                           ``model="claude-haiku-4-5-20251001"`` so this
                           daily summarisation runs on Haiku to save cost.

    Output: logs/daily/DESKTOP-LOGS-DD-MM-YYYY.md
    """
    cfg_id__anthropic = kwargs.get('cfg_id__anthropic', 'ANTHROPIC')
    model_override = kwargs.get('model')
    try:
        anthropic = BaseApiServiceAnthropic(get_anthropic_config(cfg_id__anthropic))
    except Exception as e:
        log.error("Failed to initialize Anthropic client for daily summary")
        raise e
    resolved_model = model_override or anthropic.model

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

    # Cap to keep us under any model's context window. Without this the file
    # accumulates over time and a single call eventually overflows
    # (1.17M tokens > 1M observed in the wild).
    original_chars = len(dump_content)
    dump_content = _tail_with_marker(dump_content, MAX_DUMP_CHARS)
    if original_chars > MAX_DUMP_CHARS:
        log.warning(
            "dump.txt was %s chars; truncated to last %s for daily summary",
            f"{original_chars:,}", f"{MAX_DUMP_CHARS:,}",
        )

    try:
        # send_messages(): backoff retries AND Max -> API fallback on
        # rate-limit/quota. _with_backoff alone retries the throttled provider only.
        response = anthropic.send_messages(
            messages=[{
                "role": "user",
                "content": f"{_DAILY_SUMMARY_PROMPT}\n\nActivity log dump:\n```\n{dump_content}\n```",
            }],
            model=resolved_model,
            max_tokens=8192,
        )
        summary_md = response.content[0].text
    except Exception as e:
        # Re-raise so Celery marks the task FAILED — visible in Flower, the
        # failed-jobs HUD widget, and any retry policy. Returning "FAILED: ..."
        # as a string previously made the failure invisible to everything but
        # this log line.
        log.error("Anthropic daily summary generation failed: %s", e)
        raise

    today = datetime.now().strftime("%m-%d-%Y")
    output_dir = Path(logs_output_path).expanduser()
    output_dir.mkdir(parents=True, exist_ok=True)
    output_file = output_dir / f"DESKTOP-LOGS-{today}.md"

    output_file.write_text(summary_md, encoding='utf-8')

    log.info(f"Daily summary written to {output_file}")
    return f"SUCCESS: {output_file}"


@log_result()
@SPROUT.task()
def generate_weekly_desktop_summary(logs_daily_path='logs/daily', logs_output_path='logs/weekly', **kwargs):
    """
    Reads all daily DESKTOP-LOGS-*.md files from the past 7 days and sends them
    to Claude to produce a structured Markdown weekly highlights report.

    Kwargs:
        cfg_id__anthropic: Config key for the Anthropic client. Default 'ANTHROPIC'.
        model:             Optional model override. When omitted, falls
                           back to ``BaseApiServiceAnthropic``'s configured
                           model. The celery schedule passes
                           ``model="claude-haiku-4-5-20251001"`` so the
                           weekly roll-up runs on Haiku to save cost.

    Output: logs/weekly/DESKTOP-LOGS-WEEK-WW-YYYY.md
    """
    cfg_id__anthropic = kwargs.get('cfg_id__anthropic', 'ANTHROPIC')
    model_override = kwargs.get('model')
    try:
        anthropic = BaseApiServiceAnthropic(get_anthropic_config(cfg_id__anthropic))
    except Exception as e:
        log.error("Failed to initialize Anthropic client for weekly summary")
        raise e
    resolved_model = model_override or anthropic.model

    today = datetime.now()
    week_num = today.strftime("%W")
    year = today.strftime("%Y")

    daily_dir = Path(logs_daily_path).expanduser()
    if not daily_dir.is_dir():
        log.warning(f"Daily logs directory not found at {daily_dir} — skipping weekly summary")
        return "SKIPPED: daily logs directory not found"

    daily_files = []
    for i in range(7):
        day = today - timedelta(days=i)
        filename = f"DESKTOP-LOGS-{day.strftime('%m-%d-%Y')}.md"
        filepath = daily_dir / filename
        if filepath.exists():
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
    # Same cap as the daily task — defensive: daily summaries are usually
    # small (~5-30KB each, capped at 8192 output tokens) but if an upstream
    # change ever inlines raw dumps this still won't overflow.
    original_chars = len(combined_content)
    combined_content = _tail_with_marker(combined_content, MAX_DUMP_CHARS)
    if original_chars > MAX_DUMP_CHARS:
        log.warning(
            "Weekly combined content was %s chars; truncated to last %s",
            f"{original_chars:,}", f"{MAX_DUMP_CHARS:,}",
        )
    prompt = (
        f"{_WEEKLY_SUMMARY_PROMPT}\n\n"
        f"Week number: {week_num}\n"
        f"Date range: {week_start} – {week_end}\n\n"
        f"Daily summaries:\n\n{combined_content}"
    )

    try:
        # send_messages(): backoff retries AND Max -> API fallback on
        # rate-limit/quota. _with_backoff alone retries the throttled provider only.
        response = anthropic.send_messages(
            messages=[{"role": "user", "content": prompt}],
            model=resolved_model,
            max_tokens=8192,
        )
        summary_md = response.content[0].text
    except Exception as e:
        # Re-raise so Celery sees the failure — see daily task for rationale.
        log.error("Anthropic weekly summary generation failed: %s", e)
        raise

    output_dir = Path(logs_output_path).expanduser()
    output_dir.mkdir(parents=True, exist_ok=True)
    output_file = output_dir / f"DESKTOP-LOGS-WEEK-{week_num}-{year}.md"

    output_file.write_text(summary_md, encoding='utf-8')

    log.info(f"Weekly summary written to {output_file}")
    return f"SUCCESS: {output_file}"
