#  region Try to call rainmeter without stealing focus

import subprocess
from pathlib import Path

from apps.desktop.helpers.feed import _path_lock

# Adjust this if Rainmeter is installed in a different path
RAINMETER_EXE = Path(r"C:\Program Files\Rainmeter\Rainmeter.exe")
RAINMETER_COMMAND_TIMEOUT_SECS = 5.0



def _send_rainmeter_cmd_no_focus(*args: str) -> None:
    """
    Call Rainmeter.exe with native command-line arguments, without
    opening a visible console window.

    Example:
        _send_rainmeter_cmd_no_focus("!ActivateConfig", "MySkin\\HUD", "HUD.ini")
        _send_rainmeter_cmd_no_focus("!DeactivateConfig", "MySkin\\HUD")
        _send_rainmeter_cmd_no_focus("!RefreshApp")
    """
    if not RAINMETER_EXE.exists():
        raise RuntimeError(f"Rainmeter.exe not found at: {RAINMETER_EXE}")

    startupinfo = subprocess.STARTUPINFO()
    startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
    startupinfo.wShowWindow = 0  # SW_HIDE

    CREATE_NO_WINDOW = 0x08000000

    try:
        # Rainmeter forwards CLI bangs to its running instance. If that
        # instance hangs, an unbounded subprocess call exhausts every thread in
        # the HUD worker and causes queued tasks to stampede after a restart.
        with _path_lock(
            RAINMETER_EXE,
            timeout=RAINMETER_COMMAND_TIMEOUT_SECS,
        ) as acquired:
            if not acquired:
                raise RuntimeError(
                    "Timed out waiting for the Rainmeter command channel"
                )
            subprocess.run(
                [str(RAINMETER_EXE), *args],
                check=False,
                startupinfo=startupinfo,
                creationflags=CREATE_NO_WINDOW,
                timeout=RAINMETER_COMMAND_TIMEOUT_SECS,
            )
    except subprocess.TimeoutExpired as e:
        raise RuntimeError(
            f"Rainmeter command timed out after {RAINMETER_COMMAND_TIMEOUT_SECS:g}s "
            f"with args={args!r}"
        ) from e
    except Exception as e:
        raise RuntimeError(f"Failed to call Rainmeter with args={args!r}") from e


# -------------------------------------------------
# Public API (signatures kept intact)
# -------------------------------------------------
def _activate_config(skin_name: str, hud_dir: str, ini_filename: str) -> None:
    """
    Activate a Rainmeter config.
    """
    config = f"{skin_name}\\{hud_dir}" if hud_dir else skin_name
    # No extra quotes needed; each arg is its own parameter.
    _send_rainmeter_cmd_no_focus("!ActivateConfig", config, ini_filename)


def _deactivate_config(skin_name: str, hud_dir: str) -> None:
    """
    Deactivate a Rainmeter config.
    """
    config = f"{skin_name}\\{hud_dir}" if hud_dir else skin_name
    _send_rainmeter_cmd_no_focus("!DeactivateConfig", config)


def _refresh_app() -> None:
    """
    Refresh the entire Rainmeter application.
    """
    _send_rainmeter_cmd_no_focus("!RefreshApp")


def _refresh_skin(skin_name, hud_dirname) -> None: #
    """ skin_name, hud_dirname
    Refresh only the skin
    """
    config = f"{skin_name}\\{hud_dirname}"
    _send_rainmeter_cmd_no_focus("!Refresh", config)

# endregion
