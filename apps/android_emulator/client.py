"""apps/android_emulator/client.py

Thin, testable wrapper around the Android SDK command-line tools
(emulator / adb / avdmanager / sdkmanager). Every public function returns plain
Python data (dicts / lists / CmdResult) and never raises for an *operational*
failure — a missing SDK or a non-zero tool exit comes back as a structured
result so the MCP layer and the Celery tasks can both surface it cleanly.

The only long-running, non-blocking call is `start_emulator`, which spawns the
emulator detached (it runs until killed) and returns immediately with the
console port + pid. Use `wait_for_boot` / `list_running` to observe it.
"""
from __future__ import annotations

import logging
import os
import re
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path

from apps.android_emulator import config

logger = logging.getLogger("harqis-app.android_emulator")

_DEFAULT_TIMEOUT = 120


@dataclass
class CmdResult:
    ok: bool
    returncode: int
    stdout: str
    stderr: str

    def as_dict(self) -> dict:
        return {
            "success": self.ok,
            "returncode": self.returncode,
            "stdout": self.stdout.strip(),
            "stderr": self.stderr.strip(),
        }


def _run(tool: str, args: list[str], *, timeout: int = _DEFAULT_TIMEOUT,
         input_text: str | None = None) -> CmdResult:
    """Run an SDK tool synchronously and capture output."""
    path = config.tool_path(tool)
    if path is None:
        return CmdResult(
            False, 127, "",
            f"{tool} not found — Android SDK not installed/resolved on this host "
            f"(set ANDROID_SDK_ROOT or install the SDK).",
        )
    cmd = [str(path), *args]
    logger.info("android_emulator: run %s %s", tool, " ".join(args))
    try:
        proc = subprocess.run(
            cmd, capture_output=True, text=True, timeout=timeout,
            input=input_text, env=config.tool_env(),
        )
        return CmdResult(proc.returncode == 0, proc.returncode,
                         proc.stdout or "", proc.stderr or "")
    except subprocess.TimeoutExpired:
        return CmdResult(False, -1, "", f"{tool} timed out after {timeout}s")
    except Exception as exc:  # noqa: BLE001 - surface as data, never crash caller
        return CmdResult(False, -1, "", f"{tool} failed: {exc}")


# ── AVD management ──────────────────────────────────────────────────────────

def list_avds() -> list[str]:
    """Names of installed AVDs (avdmanager list avd -c)."""
    res = _run("avdmanager", ["list", "avd", "-c"])
    if not res.ok:
        return []
    return [ln.strip() for ln in res.stdout.splitlines() if ln.strip()]


def list_system_images() -> list[str]:
    """Installed `system-images;...` package paths (sdkmanager --list_installed)."""
    res = _run("sdkmanager", ["--list_installed"], timeout=180)
    if not res.ok:
        return []
    out = []
    for ln in res.stdout.splitlines():
        token = ln.strip().split()[0] if ln.strip() else ""
        if token.startswith("system-images;"):
            out.append(token)
    return out


def create_avd(name: str, image: str, *, device: str | None = None,
               force: bool = False) -> CmdResult:
    """Create an AVD. Feeds 'no' to the 'custom hardware profile?' prompt."""
    args = ["create", "avd", "-n", name, "-k", image]
    if device:
        args += ["-d", device]
    if force:
        args += ["--force"]
    return _run("avdmanager", args, input_text="no\n")


def delete_avd(name: str) -> CmdResult:
    return _run("avdmanager", ["delete", "avd", "-n", name])


# ── Persistent AVD config (config.ini hardware props) ───────────────────────

# Profile bool keys → persistent config.ini hardware properties. These are read
# by the emulator at boot, so patching config.ini makes a setting stick for
# *every* future launch of the AVD (unlike runtime flags). Add more as needed.
_AVD_HW_PROP_MAP = {
    "hw_keyboard": "hw.keyboard",      # host hardware-keyboard passthrough (yes/no)
    "play_store": "PlayStore.enabled",  # certified Google Play (needs a *_playstore image)
}


def _avd_home() -> Path:
    """Dir holding the `<name>.avd` folders. Respects ANDROID_AVD_HOME /
    ANDROID_SDK_HOME, else the conventional ~/.android/avd."""
    avd_home = (os.environ.get("ANDROID_AVD_HOME") or "").strip()
    if avd_home:
        return Path(avd_home)
    sdk_home = (os.environ.get("ANDROID_SDK_HOME")
                or os.environ.get("ANDROID_PREFS_ROOT") or "").strip()
    if sdk_home:
        return Path(sdk_home) / ".android" / "avd"
    return Path.home() / ".android" / "avd"


def _avd_config_ini(avd_name: str) -> Path:
    return _avd_home() / f"{avd_name}.avd" / "config.ini"


def _ini_props_from_cfg(cfg: dict) -> dict:
    """Translate a merged profile's bool toggles into config.ini key=value strs."""
    out: dict = {}
    for key, ini_key in _AVD_HW_PROP_MAP.items():
        if cfg.get(key) is not None:
            out[ini_key] = "yes" if cfg[key] else "no"
    return out


def ensure_avd_ini_props(avd_name: str, props: dict) -> dict:
    """Idempotently set `key=value` lines in an AVD's config.ini.

    Only rewrites the file when a value actually changes, so repeat launches
    don't churn the file (or needlessly invalidate the boot snapshot). Missing
    keys are appended. Returns {"success", "changed": [...], "path"}.
    """
    if not props:
        return {"success": True, "changed": [], "path": None}
    path = _avd_config_ini(avd_name)
    try:
        if not path.is_file():
            return {"success": False,
                    "error": f"config.ini not found for AVD {avd_name!r} at {path}"}
        text = path.read_text(encoding="utf-8")
    except Exception as exc:  # noqa: BLE001
        return {"success": False, "error": f"reading {path}: {exc}"}

    newline = "\r\n" if "\r\n" in text else "\n"
    remaining = dict(props)
    changed: list[str] = []
    out_lines: list[str] = []
    for ln in text.splitlines():
        key = ln.split("=", 1)[0].strip() if "=" in ln else None
        if key in remaining:
            desired = f"{key}={remaining.pop(key)}"
            if ln != desired:
                changed.append(key)
            out_lines.append(desired)
        else:
            out_lines.append(ln)
    for key, val in remaining.items():  # not present yet → append
        out_lines.append(f"{key}={val}")
        changed.append(key)

    if changed:
        try:
            path.write_text(newline.join(out_lines) + newline, encoding="utf-8")
        except Exception as exc:  # noqa: BLE001
            return {"success": False, "error": f"writing {path}: {exc}"}
        logger.info("android_emulator: patched %s -> %s", path, changed)
    return {"success": True, "changed": changed, "path": str(path)}


# ── Parallel instances & cloning ────────────────────────────────────────────

# Console ports are even, 5554-5682; adb binds port+1. We skip 5554 by default
# because its adb port (5555) is commonly squatted (e.g. Docker/WSL on this host).
_PORT_MIN, _PORT_MAX = 5554, 5682
_DEFAULT_SKIP_PORTS = {5554}


def free_console_port(preferred: int | None = None,
                      skip: set | None = None) -> int | None:
    """Pick a free even console port, preferring `preferred` if it's free.

    "Free" = not currently bound by a running emulator (and not in `skip` /
    the default-skip set). Returns None if the whole range is taken.
    """
    used = {d["port"] for d in list_running() if d.get("port")}
    used |= _DEFAULT_SKIP_PORTS | (skip or set())
    order = []
    if preferred is not None and preferred % 2 == 0:
        order.append(preferred)
    order += list(range(_PORT_MIN, _PORT_MAX + 1, 2))
    for p in order:
        if p not in used:
            return p
    return None


def spawn(profile: str | None = None, name: str | None = None,
          port: int | None = None, overrides: dict | None = None) -> dict:
    """Create-if-needed and launch an instance from a profile on a *free* port.

    Each `name` is its own AVD with independent, persistent state; multiple
    spawns (distinct names) run in parallel, each auto-assigned a free console
    port. The profile supplies device/image/resources and the persistent toggles
    (hw_keyboard/play_store/nav_mode), applied per instance. Returns the launch
    dict (with the resolved `port`/`serial`), or an error.
    """
    try:
        cfg = config.merge_profile(profile, overrides)
    except KeyError as exc:
        return {"success": False, "error": str(exc)}
    avd = name or cfg.get("profile")
    if not avd:
        return {"success": False, "error": "no name and no profile to derive one"}
    if avd not in list_avds():
        res = create_from_profile(profile=profile, name=avd, overrides=overrides)
        if not res.ok:
            return {"success": False, "stage": "create",
                    "error": res.stderr or res.stdout or "create failed"}
    chosen = free_console_port(port if port is not None else cfg.get("port"))
    if chosen is None:
        return {"success": False,
                "error": f"no free console port in {_PORT_MIN}-{_PORT_MAX}"}
    ov = dict(overrides or {})
    ov["port"] = chosen
    return launch(profile=profile, avd_name=avd, overrides=ov)


# Per-instance state lives in these; the *.lock files and the live snapshots dir
# are intentionally NOT copied (they're instance/run-bound), so the clone cold-
# boots fresh but inherits the source's saved userdata (installed apps, files,
# settings) — i.e. its "saved data state".
_CLONE_IGNORE = shutil.ignore_patterns("*.lock", "snapshots", "*.qcow2.lock",
                                        "hardware-qemu.ini", "emulator-user.ini")


def clone_avd(src_name: str, dst_name: str, *, force: bool = False) -> dict:
    """Duplicate an AVD (with its saved userdata) under a new name.

    The clone is an independent AVD that boots from a copy of the source's data
    partition. Stop the source first for a clean, fully-flushed copy. Returns
    {"success", "src", "dst", "path"} or an error.
    """
    home = _avd_home()
    src_dir, dst_dir = home / f"{src_name}.avd", home / f"{dst_name}.avd"
    src_ini, dst_ini = home / f"{src_name}.ini", home / f"{dst_name}.ini"
    if not src_dir.is_dir():
        return {"success": False,
                "error": f"source AVD {src_name!r} not found at {src_dir}"}
    if dst_dir.exists() or dst_ini.exists():
        if not force:
            return {"success": False,
                    "error": f"target AVD {dst_name!r} already exists (use force=True)"}
        shutil.rmtree(dst_dir, ignore_errors=True)
        dst_ini.unlink(missing_ok=True)
    try:
        shutil.copytree(src_dir, dst_dir, ignore=_CLONE_IGNORE)
        # Top-level <name>.ini points the SDK at the .avd dir — repoint it.
        # Use literal (callable) replacements so backslashes in Windows paths
        # aren't interpreted as regex escape sequences (e.g. \U in \Users).
        if src_ini.is_file():
            text = src_ini.read_text(encoding="utf-8")
            text = re.sub(r"(?m)^path=.*$", lambda _: f"path={dst_dir}", text)
            text = re.sub(r"(?m)^path\.rel=.*$",
                          lambda _: f"path.rel=avd\\{dst_name}.avd", text)
            dst_ini.write_text(text, encoding="utf-8")
        # Rename the AVD inside its own config.ini where present.
        cfg_ini = dst_dir / "config.ini"
        if cfg_ini.is_file():
            ctext = cfg_ini.read_text(encoding="utf-8")
            for key in ("AvdId", "avd.id", "avd.name"):
                ctext = re.sub(rf"(?m)^{re.escape(key)}=.*$",
                               lambda _, k=key: f"{k}={dst_name}", ctext)
            cfg_ini.write_text(ctext, encoding="utf-8")
    except Exception as exc:  # noqa: BLE001
        return {"success": False, "error": f"clone failed: {exc}"}
    logger.info("android_emulator: cloned AVD %s -> %s", src_name, dst_name)
    return {"success": True, "src": src_name, "dst": dst_name, "path": str(dst_dir)}


# ── Emulator lifecycle ──────────────────────────────────────────────────────

def _serial_for_port(port: int) -> str:
    return f"emulator-{port}"


def start_emulator(avd_name: str, *, port: int | None = None,
                   headless: bool = True, no_audio: bool = True,
                   no_snapshot: bool = False, wipe_data: bool = False,
                   gpu: str | None = "auto", memory_mb: int | None = None,
                   cores: int | None = None, partition_mb: int | None = None,
                   extra_args: list[str] | None = None) -> dict:
    """Launch an AVD detached. Returns immediately (the emulator keeps running).

    `memory_mb` / `cores` / `partition_mb` map to the emulator's `-memory`,
    `-cores`, `-partition-size` flags so a profile's RAM/CPU/storage apply at
    launch without editing the AVD's config.ini.

    Returns {"success", "pid", "port", "serial", "avd", "args"} or
    {"success": False, "error": ...} if the emulator binary is missing.
    """
    emu = config.tool_path("emulator")
    if emu is None:
        return {"success": False, "error": "emulator not found — SDK not resolved",
                "avd": avd_name}

    # Headless boots need a software renderer — `-gpu auto` selects a host GPU
    # mode that requires a display and crashes with `-no-window`. Default
    # headless launches to swiftshader unless the caller picked a GPU explicitly.
    if headless and gpu in (None, "auto"):
        gpu = "swiftshader_indirect"

    args: list[str] = ["-avd", avd_name]
    if port is not None:
        args += ["-port", str(port)]
    if headless:
        args += ["-no-window", "-no-boot-anim"]
    if no_audio:
        args += ["-no-audio"]
    if no_snapshot:
        args += ["-no-snapshot"]
    if wipe_data:
        args += ["-wipe-data"]
    if gpu:
        args += ["-gpu", gpu]
    if memory_mb:
        args += ["-memory", str(memory_mb)]
    if cores:
        args += ["-cores", str(cores)]
    if partition_mb:
        # The emulator rejects a -partition-size outside 10..2047 MB and exits
        # immediately, so an out-of-range profile value would kill every launch.
        # Clamp-skip instead: warn and omit rather than pass a fatal flag. (The
        # data partition is sized by the AVD's config.ini, not this flag.)
        if 10 <= int(partition_mb) <= 2047:
            args += ["-partition-size", str(partition_mb)]
        else:
            logger.warning("android_emulator: ignoring partition_mb=%s "
                           "(valid -partition-size is 10-2047 MB)", partition_mb)
    if extra_args:
        args += list(extra_args)

    cmd = [str(emu), *args]
    logger.info("android_emulator: start %s", " ".join(cmd))
    # Detach so the emulator outlives this process / request.
    kwargs: dict = {}
    if sys.platform == "win32":
        # CREATE_NEW_PROCESS_GROUP keeps the emulator alive past this request.
        # DETACHED_PROCESS additionally severs it from the console *and* the
        # interactive window station — fine when headless, but it crashes a
        # windowed launch (the Qt GUI can't create its window off-station).
        # So only fully detach for headless boots; windowed launches stay
        # attached to the desktop so the UI window can appear.
        kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP
        if headless:
            kwargs["creationflags"] |= 0x00000008  # DETACHED_PROCESS
    else:
        kwargs["start_new_session"] = True
    try:
        proc = subprocess.Popen(
            cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            stdin=subprocess.DEVNULL, env=config.tool_env(), **kwargs,
        )
    except Exception as exc:  # noqa: BLE001
        return {"success": False, "error": f"failed to launch emulator: {exc}",
                "avd": avd_name}

    resolved_port = port if port is not None else 5554
    return {
        "success": True,
        "pid": proc.pid,
        "port": resolved_port,
        "serial": _serial_for_port(resolved_port),
        "avd": avd_name,
        "args": args,
    }


_LAUNCH_KEYS = ("port", "headless", "no_audio", "no_snapshot", "wipe_data",
                "gpu", "memory_mb", "cores", "partition_mb")


def launch(profile: str | None = None, avd_name: str | None = None,
           overrides: dict | None = None) -> dict:
    """Resolve a profile (+overrides) and start the matching AVD.

    The AVD name defaults to the profile name (the convention used by
    `create_from_profile`). Launch flags (port/headless/ram/cores/...) come from
    the merged profile config; `ram_mb`/`partition_mb` profile keys map to the
    `memory_mb`/`partition_mb` launch params.
    """
    cfg = config.merge_profile(profile, overrides)
    name = avd_name or cfg.get("profile")
    if not name:
        return {"success": False,
                "error": "no avd_name and no profile/default_profile to derive one"}
    # Persist hardware props (e.g. host keyboard passthrough) into the AVD's
    # config.ini *before* boot so every launch of this profile inherits them.
    ensure_avd_ini_props(name, _ini_props_from_cfg(cfg))
    # Map profile field names → start_emulator kwargs.
    kwargs = {k: cfg[k] for k in _LAUNCH_KEYS if k in cfg}
    if "ram_mb" in cfg:
        kwargs.setdefault("memory_mb", cfg["ram_mb"])
    return start_emulator(name, **kwargs)


def create_from_profile(profile: str | None = None, name: str | None = None,
                        overrides: dict | None = None,
                        force: bool = False) -> CmdResult:
    """Create an AVD from a profile's device+image (name defaults to profile)."""
    cfg = config.merge_profile(profile, overrides)
    avd = name or cfg.get("profile")
    image = cfg.get("image")
    if not avd or not image:
        return CmdResult(False, 2, "",
                         "profile must supply an 'image' (and a name); got "
                         f"name={avd!r} image={image!r}")
    res = create_avd(avd, image, device=cfg.get("device"), force=force)
    if res.ok:
        # Stamp persistent hardware props onto the freshly created AVD so a new
        # instance is born with them (avdmanager defaults hw.keyboard to "no").
        ensure_avd_ini_props(avd, _ini_props_from_cfg(cfg))
    return res


def list_running() -> list[dict]:
    """Running emulator devices from `adb devices` → [{serial, port, state}]."""
    res = _run("adb", ["devices"])
    if not res.ok:
        return []
    out = []
    for ln in res.stdout.splitlines():
        ln = ln.strip()
        if not ln or ln.startswith("List of devices"):
            continue
        parts = ln.split()
        serial = parts[0]
        state = parts[1] if len(parts) > 1 else "unknown"
        if serial.startswith("emulator-"):
            try:
                port = int(serial.split("-", 1)[1])
            except ValueError:
                port = None
            out.append({"serial": serial, "port": port, "state": state})
    return out


def boot_completed(serial: str) -> bool:
    """True once `sys.boot_completed` == 1 for the device."""
    res = _run("adb", ["-s", serial, "shell", "getprop", "sys.boot_completed"],
               timeout=15)
    return res.ok and res.stdout.strip() == "1"


def wait_for_boot(serial: str, *, timeout: int = 180,
                  poll_secs: float = 3.0) -> dict:
    """Block until the device finishes booting or `timeout` elapses."""
    res = _run("adb", ["-s", serial, "wait-for-device"], timeout=timeout)
    if not res.ok:
        return {"success": False, "serial": serial, "booted": False,
                "error": res.stderr or "wait-for-device failed"}
    waited = 0.0
    while waited < timeout:
        if boot_completed(serial):
            return {"success": True, "serial": serial, "booted": True,
                    "waited_secs": round(waited, 1)}
        time.sleep(poll_secs)
        waited += poll_secs
    return {"success": False, "serial": serial, "booted": False,
            "error": f"boot not completed within {timeout}s"}


def stop_emulator(serial: str) -> CmdResult:
    """Gracefully kill a running emulator via the console (`adb emu kill`)."""
    return _run("adb", ["-s", serial, "emu", "kill"], timeout=30)


def status(serial: str) -> dict:
    """Lifecycle snapshot for one emulator serial."""
    running = {d["serial"]: d for d in list_running()}
    if serial not in running:
        return {"serial": serial, "running": False, "booted": False}
    return {
        "serial": serial,
        "running": True,
        "state": running[serial].get("state"),
        "booted": boot_completed(serial),
    }


# ── Device operations ───────────────────────────────────────────────────────

def install_apk(serial: str, apk_path: str, *, reinstall: bool = True) -> CmdResult:
    args = ["-s", serial, "install"]
    if reinstall:
        args.append("-r")
    args.append(apk_path)
    return _run("adb", args, timeout=300)


def uninstall_package(serial: str, package: str) -> CmdResult:
    return _run("adb", ["-s", serial, "uninstall", package])


def adb_shell(serial: str, command: list[str], *, timeout: int = 60) -> CmdResult:
    """Run an adb shell command. The MCP layer enforces a command whitelist;
    the Celery task may pass through. `command` is a pre-split argv list."""
    return _run("adb", ["-s", serial, "shell", *command], timeout=timeout)


def screenshot(serial: str, dest_path: str) -> dict:
    """Capture a PNG screenshot to `dest_path` on the host.

    `adb exec-out screencap -p` returns raw PNG bytes on stdout, so this runs
    adb in binary mode (NOT the text-mode `_run`, which would corrupt the image
    and throw a decode error) and writes the bytes straight to disk.
    """
    path = config.tool_path("adb")
    if path is None:
        return {"success": False, "error": "adb not found"}
    try:
        proc = subprocess.run(
            [str(path), "-s", serial, "exec-out", "screencap", "-p"],
            capture_output=True, timeout=60, env=config.tool_env(),
        )
        if proc.returncode != 0:
            return {"success": False,
                    "error": (proc.stderr or b"").decode("utf-8", "replace")}
        with open(dest_path, "wb") as fh:
            fh.write(proc.stdout)
        return {"success": True, "path": dest_path, "bytes": len(proc.stdout)}
    except Exception as exc:  # noqa: BLE001
        return {"success": False, "error": f"screenshot failed: {exc}"}


# ── Guest settings (post-boot) ──────────────────────────────────────────────

# On-screen navigation modes → the system RRO overlay that enables them.
# Enabling one disables the others in the (mutually-exclusive) navbar category,
# so this both sets e.g. three-button nav *and* clears gesture nav.
_NAV_OVERLAYS = {
    "threebutton": "com.android.internal.systemui.navbar.threebutton",
    "twobutton":   "com.android.internal.systemui.navbar.twobutton",
    "gestural":    "com.android.internal.systemui.navbar.gestural",
}


def apply_nav_mode(serial: str, mode: str) -> CmdResult:
    """Set on-screen navigation (threebutton/twobutton/gestural) on a booted
    device. The choice persists in guest userdata across reboots."""
    overlay = _NAV_OVERLAYS.get(str(mode))
    if overlay is None:
        return CmdResult(False, 2, "",
                         f"unknown nav_mode {mode!r}; expected {sorted(_NAV_OVERLAYS)}")
    return _run("adb", ["-s", serial, "shell", "cmd", "overlay", "enable", overlay],
                timeout=30)


def apply_post_boot_settings(serial: str, profile: str | None = None,
                             overrides: dict | None = None) -> dict:
    """Apply profile-driven guest settings that need a *booted* device.

    Currently the on-screen navigation mode (`nav_mode`). These persist in guest
    userdata, so they effectively only need applying once per AVD; re-applying on
    later boots is cheap and harmless. Returns {"success", "applied": {...}}.
    """
    try:
        cfg = config.merge_profile(profile, overrides)
    except KeyError as exc:
        return {"success": False, "error": str(exc)}
    applied: dict = {}
    mode = cfg.get("nav_mode")
    if mode:
        applied["nav_mode"] = apply_nav_mode(serial, mode).as_dict()
    return {"success": True, "applied": applied}


# ── Snapshots ───────────────────────────────────────────────────────────────

def snapshot_save(serial: str, name: str) -> CmdResult:
    return _run("adb", ["-s", serial, "emu", "avd", "snapshot", "save", name],
                timeout=120)


def snapshot_load(serial: str, name: str) -> CmdResult:
    return _run("adb", ["-s", serial, "emu", "avd", "snapshot", "load", name],
                timeout=120)


def snapshot_list(serial: str) -> CmdResult:
    return _run("adb", ["-s", serial, "emu", "avd", "snapshot", "list"],
                timeout=60)
