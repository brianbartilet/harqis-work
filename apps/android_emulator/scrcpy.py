"""apps/android_emulator/scrcpy.py

Mirror + control a device's screen on the host via scrcpy (the standard
open-source Android mirroring tool). Used for hands-on testing of a *physical*
device — e.g. apps with RASP/anti-tamper that refuse to run on an emulator:
scrcpy only mirrors the display and forwards input through adb, so it doesn't
root, hook, debug, instrument, or modify the app, and the device passes its
integrity checks.

scrcpy is an optional external dependency:
  - Windows : winget install Genymobile.scrcpy
  - macOS   : brew install scrcpy
  - Linux   : apt install scrcpy  (or the snap)

resolve_scrcpy() finds it on PATH, via an ANDROID_EMULATOR.scrcpy_path config
override, or at the conventional winget install location on Windows.
"""
from __future__ import annotations

import logging
import os
import shutil
import subprocess
import sys
from pathlib import Path

from apps.android_emulator import config

logger = logging.getLogger("harqis-app.android_emulator")


def resolve_scrcpy() -> Path | None:
    """Locate the scrcpy executable, or None if it isn't installed.

    Precedence: ANDROID_EMULATOR.scrcpy_path in apps_config.yaml → PATH →
    the winget install location on Windows (Links shim, then the versioned
    package dir).
    """
    cfg = config._config_section().get("scrcpy_path")
    if cfg and "${" not in str(cfg):
        p = Path(str(cfg)).expanduser()
        if p.is_file():
            return p

    found = shutil.which("scrcpy")
    if found:
        return Path(found)

    if sys.platform == "win32":
        local = os.environ.get("LOCALAPPDATA") or str(Path.home() / "AppData" / "Local")
        candidates = [Path(local) / "Microsoft" / "WinGet" / "Links" / "scrcpy.exe"]
        pkgs = Path(local) / "Microsoft" / "WinGet" / "Packages"
        if pkgs.is_dir():
            candidates += sorted(
                pkgs.glob("Genymobile.scrcpy*/scrcpy-win64-*/scrcpy.exe"),
                reverse=True,  # newest version first
            )
        for c in candidates:
            if c.is_file():
                return c
    return None


def scrcpy_available() -> bool:
    return resolve_scrcpy() is not None


def start_mirror(serial: str | None = None, *, title: str | None = None,
                 max_size: int | None = None, bitrate: str | None = None,
                 stay_awake: bool = True, turn_screen_off: bool = False,
                 extra_args: list[str] | None = None) -> dict:
    """Launch a scrcpy mirror window for `serial`, detached. Returns immediately.

    `stay_awake` keeps the device awake while plugged in; `turn_screen_off`
    blanks the *device* screen while still mirroring (saves battery/heat).
    Returns {"success", "pid", "serial", "args"} or {"success": False, "error"}.
    """
    exe = resolve_scrcpy()
    if exe is None:
        return {"success": False,
                "error": "scrcpy not found — install it (Windows: "
                         "winget install Genymobile.scrcpy)"}

    args: list[str] = [str(exe)]
    if serial:
        args += ["-s", serial]
    if title:
        args += ["--window-title", title]
    if max_size:
        args += ["--max-size", str(max_size)]
    if bitrate:
        args += ["--video-bit-rate", str(bitrate)]
    if stay_awake:
        args += ["--stay-awake"]
    if turn_screen_off:
        args += ["--turn-screen-off"]
    if extra_args:
        args += list(extra_args)

    # Point scrcpy at the SAME adb the rest of the app uses, so it doesn't
    # start a second (possibly version-mismatched) adb server and bounce the
    # connection to other devices/emulators.
    env = dict(os.environ)
    adb = config.tool_path("adb")
    if adb is not None:
        env["ADB"] = str(adb)

    # Detach so the window outlives this request, but DON'T fully detach from
    # the window station (DETACHED_PROCESS) — that kills the GUI window, the
    # same lesson learned with the emulator's windowed launch.
    kwargs: dict = {}
    if sys.platform == "win32":
        kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP
    else:
        kwargs["start_new_session"] = True

    logger.info("android_emulator: scrcpy %s", " ".join(args[1:]))
    try:
        proc = subprocess.Popen(
            args, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            stdin=subprocess.DEVNULL, env=env, **kwargs,
        )
    except Exception as exc:  # noqa: BLE001
        return {"success": False, "error": f"failed to launch scrcpy: {exc}"}
    return {"success": True, "pid": proc.pid, "serial": serial, "args": args[1:]}


def mirror_pids(serial: str | None = None) -> list[int]:
    """PIDs of running scrcpy mirror(s) (optionally just those targeting `serial`)."""
    pids: list[int] = []
    if sys.platform == "win32":
        ps = "Get-CimInstance Win32_Process -Filter \"Name='scrcpy.exe'\""
        if serial:
            ps += f" | Where-Object {{ $_.CommandLine -like '*{serial}*' }}"
        ps += " | Select-Object -ExpandProperty ProcessId"
        r = subprocess.run(["powershell", "-NoProfile", "-Command", ps],
                           capture_output=True, text=True, check=False)
    else:
        pattern = f"scrcpy.*{serial}" if serial else "scrcpy"
        r = subprocess.run(["pgrep", "-f", pattern],
                           capture_output=True, text=True, check=False)
    for tok in r.stdout.split():
        if tok.strip().isdigit():
            pids.append(int(tok))
    return pids


def mirror_running(serial: str | None = None) -> bool:
    """True if a scrcpy mirror (optionally for `serial`) is alive."""
    return bool(mirror_pids(serial))


def stop_mirror(serial: str | None = None) -> dict:
    """Kill running scrcpy mirror(s).

    With `serial`, only kills scrcpy processes whose command line targets that
    serial; otherwise kills every scrcpy. Returns {"success", "killed": [pids]}.
    """
    killed: list[int] = []
    for pid in mirror_pids(serial):
        if sys.platform == "win32":
            subprocess.run(["taskkill", "/PID", str(pid), "/T", "/F"],
                           capture_output=True, check=False)
            killed.append(pid)
        else:
            try:
                os.kill(pid, 15)
                killed.append(pid)
            except OSError:
                pass
    return {"success": True, "killed": killed}
