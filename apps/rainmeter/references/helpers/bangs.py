#  region Try to call rainmeter without stealing focus

import subprocess
from pathlib import Path

# Adjust this if Rainmeter is installed in a different path
RAINMETER_EXE = Path(r"C:\Program Files\Rainmeter\Rainmeter.exe")


def _send_rainmeter_bang_no_focus(bang: str) -> None:
    """
    Send a bang to Rainmeter using its native command-line interface,
    without opening a visible console window.

    Example bang values:
        '!ActivateConfig "MySkin\\HUD" "HUD.ini"'
        '!DeactivateConfig "MySkin\\HUD"'
        '!RefreshApp'
    """
    if not RAINMETER_EXE.exists():
        raise RuntimeError(f"Rainmeter.exe not found at: {RAINMETER_EXE}")

    # Hide console window
    startupinfo = subprocess.STARTUPINFO()
    startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
    startupinfo.wShowWindow = 0  # SW_HIDE

    CREATE_NO_WINDOW = 0x08000000

    # Pass the bang as a single argument; Rainmeter will parse it.
    # Equivalent to: Rainmeter.exe !ActivateConfig "Config" "Skin.ini"
    try:
        subprocess.run(
            [str(RAINMETER_EXE), bang],
            check=False,
            startupinfo=startupinfo,
            creationflags=CREATE_NO_WINDOW,
        )
    except Exception as e:
        raise RuntimeError(f"Failed to send bang to Rainmeter: {bang!r}") from e


# -------------------------------------------------
# Public API (signatures kept intact)
# -------------------------------------------------
def _activate_config(skin_name: str, hud_dir: str, ini_filename: str) -> None:
    """
    Activate a Rainmeter config.

    Args:
        skin_name: Top-level skin folder name.
        hud_dir:   Subfolder config ('' for none).
        ini_filename: Name of the .ini file to load.
    """
    config = f'{skin_name}\\{hud_dir}' if hud_dir else skin_name
    bang = f'!ActivateConfig "{config}" "{ini_filename}"'
    _send_rainmeter_bang_no_focus(bang)


def _deactivate_config(skin_name: str, hud_dir: str) -> None:
    """
    Deactivate a Rainmeter config.

    Args:
        skin_name: Top-level skin folder name.
        hud_dir:   Subfolder config ('' for none).
    """
    config = f'{skin_name}\\{hud_dir}' if hud_dir else skin_name
    bang = f'!DeactivateConfig "{config}"'
    _send_rainmeter_bang_no_focus(bang)


def _refresh_app() -> None:
    """Refresh the entire Rainmeter application."""
    _send_rainmeter_bang_no_focus("!RefreshApp")


# endregion
