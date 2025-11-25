import os
import sys
import subprocess
from pathlib import Path
from datetime import datetime
import psutil

from core.apps.sprout.app.celery import SPROUT
from core.apps.es_logging.app.elasticsearch import log_result
from apps.apps_config import CONFIG_MANAGER

SCREENREADER_MARKER = "--desktop-screenreader"

# Windows flags
if os.name == "nt":
    HIDDEN_WINDOW = subprocess.CREATE_NO_WINDOW
    SHOW_WINDOW   = subprocess.CREATE_NEW_CONSOLE
else:
    HIDDEN_WINDOW = 0
    SHOW_WINDOW   = 0


def _kill_existing_screenreader_processes():
    """
    Find and terminate any existing background screenreader processes.
    """
    for proc in psutil.process_iter(["pid", "name", "cmdline"]):
        try:
            name = (proc.info.get("name") or "").lower()
            cmdline = proc.info.get("cmdline") or []

            if name in ("python.exe", "pythonw.exe") and SCREENREADER_MARKER in cmdline:
                print(f"[screenreader] Killing old PID={proc.pid}")
                proc.terminate()
                try:
                    proc.wait(timeout=3)
                except psutil.TimeoutExpired:
                    proc.kill()
        except Exception:
            continue


@SPROUT.task()
@log_result()
def run_capture_logging(cfg_id__desktop_utils):
    """
    Creates today's logfile and starts the run_capture loop
    either in a visible or hidden subprocess depending on config.
    """
    cfg = CONFIG_MANAGER.get(cfg_id__desktop_utils)

    base_path = cfg.get('actions_log_path',  os.getcwd())
    base_path = Path(base_path)
    base_path.mkdir(parents=True, exist_ok=True)

    # Determine today's logfile
    today = datetime.now().strftime("%Y%m%d_%H")
    log_file = base_path / f"actions-{today}.log"

    # Toggle flag: show or hide the console
    show_console = bool(cfg.get("show_console", False))

    # Kill old instances first
    _kill_existing_screenreader_processes()

    # Python code executed in the new subprocess
    python_code = (
        "from pathlib import Path;"
        "from core.utilities.actions_logging import run_capture;"
        f"run_capture(Path({repr(str(log_file))}))"
    )

    # Choose the correct Windows creation flag
    creation_flag = SHOW_WINDOW if show_console else HIDDEN_WINDOW

    # Launch subprocess
    subprocess.Popen(
        [sys.executable, "-c", python_code, SCREENREADER_MARKER],
        creationflags=creation_flag,
    )

    return {
        "log_file": str(log_file),
        "visible_console": show_console,
        "status": "spawned",
    }
