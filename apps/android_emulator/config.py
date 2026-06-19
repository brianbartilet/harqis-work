"""apps/android_emulator/config.py

Configuration + SDK discovery for the Android emulator app.

This is a *local-CLI* app (like apps/filesystem) — it shells out to the Android
SDK command-line tools rather than calling a REST API, so it deliberately does
NOT use apps.config_loader.get_ws_config (which builds a web-service client).
Instead it reads its own `ANDROID_EMULATOR` block from apps_config.yaml directly
and resolves the SDK location *per host* so the same code runs on any worker
that has the SDK installed (Windows / macOS / Linux).

Everything here is best-effort and import-safe: a host with no SDK still imports
cleanly. Callers check `sdk_available()` (or get a clear "not found" error from
client._run) instead of crashing at import time.

apps_config.yaml schema (all optional):

    ANDROID_EMULATOR:
      sdk_root: ${ANDROID_SDK_ROOT}      # optional; env/defaults used if unset
      default_profile: pixel7-test
      profiles:
        pixel7-test:
          device: pixel_7                # avdmanager device id (avdmanager list device)
          image: system-images;android-34;google_apis;x86_64
          ram_mb: 4096
          cores: 4
          partition_mb: 6144
          headless: true                 # -no-window
          no_audio: true                 # -no-audio
          gpu: auto                       # -gpu <mode>
          hw_keyboard: true              # host hardware-keyboard passthrough (patched into config.ini pre-boot)
          nav_mode: threebutton          # on-screen nav (threebutton/twobutton/gestural); applied in-guest post-boot
          port: 5554                      # console port (even, 5554-5682)

Two of these are not emulator launch flags: `hw_keyboard` is written to the
AVD's config.ini before boot (so it sticks for every instance), and `nav_mode`
is applied inside the booted guest via an RRO overlay (persists in userdata).
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

# Resolution precedence for the SDK root (first existing dir wins).
_ENV_VARS = ("ANDROID_SDK_ROOT", "ANDROID_HOME")

# tool name -> (sub-path under sdk, executable base name)
_TOOL_RELATIVES = {
    "emulator": ("emulator", "emulator"),
    "adb": ("platform-tools", "adb"),
    "avdmanager": ("cmdline-tools/latest/bin", "avdmanager"),
    "sdkmanager": ("cmdline-tools/latest/bin", "sdkmanager"),
}


def _config_section() -> dict:
    """Return the ANDROID_EMULATOR block, or {} if missing/unloadable."""
    try:
        from apps.apps_config import CONFIG_SERVICE
        return (CONFIG_SERVICE.config or {}).get("ANDROID_EMULATOR", {}) or {}
    except Exception:
        return {}


def _default_sdk_roots() -> list[Path]:
    """Conventional SDK install locations for the current OS."""
    home = Path.home()
    if sys.platform == "win32":
        local = os.environ.get("LOCALAPPDATA") or str(home / "AppData" / "Local")
        return [Path(local) / "Android" / "Sdk"]
    if sys.platform == "darwin":
        return [home / "Library" / "Android" / "sdk"]
    return [home / "Android" / "Sdk", home / "Android" / "sdk"]


def resolve_sdk_root() -> Path | None:
    """Resolve the Android SDK root for this host (None if not found).

    Precedence: ANDROID_SDK_ROOT/ANDROID_HOME env → ANDROID_EMULATOR.sdk_root in
    apps_config.yaml → conventional per-OS default. Returns the first candidate
    that actually exists on disk.
    """
    candidates: list[Path] = []
    for var in _ENV_VARS:
        v = (os.environ.get(var) or "").strip()
        if v:
            candidates.append(Path(v))
    cfg = _config_section().get("sdk_root")
    if cfg and "${" not in str(cfg):
        candidates.append(Path(str(cfg)))
    candidates.extend(_default_sdk_roots())

    for c in candidates:
        try:
            p = c.expanduser()
            if p.is_dir():
                return p.resolve()
        except Exception:
            continue
    return None


def tool_path(name: str) -> Path | None:
    """Absolute path to an SDK tool (emulator/adb/avdmanager/sdkmanager), or None.

    Picks the right extension per OS (.exe / .bat on Windows, none on POSIX).
    """
    if name not in _TOOL_RELATIVES:
        raise ValueError(f"unknown tool {name!r}; expected one of {list(_TOOL_RELATIVES)}")
    sdk = resolve_sdk_root()
    if sdk is None:
        return None
    subdir, base = _TOOL_RELATIVES[name]
    folder = sdk.joinpath(*subdir.split("/"))
    exts = (".exe", ".bat", "") if sys.platform == "win32" else ("",)
    for ext in exts:
        p = folder / f"{base}{ext}"
        if p.is_file():
            return p
    return None


def sdk_available() -> bool:
    """True when at least the emulator + adb binaries are resolvable here."""
    return tool_path("emulator") is not None and tool_path("adb") is not None


def _java_home_candidates() -> list[Path]:
    """Conventional JDK locations (incl. Android Studio's bundled JBR)."""
    if sys.platform == "win32":
        pf = Path(os.environ.get("ProgramFiles", r"C:\Program Files"))
        out: list[Path] = []
        for parent, pat in ((pf / "Microsoft", "jdk-17*"),
                            (pf / "Eclipse Adoptium", "jdk-17*"),
                            (pf / "Java", "jdk-17*")):
            if parent.is_dir():
                out += sorted(parent.glob(pat), reverse=True)
        out.append(pf / "Android" / "Android Studio" / "jbr")
        return out
    if sys.platform == "darwin":
        base = Path("/Library/Java/JavaVirtualMachines")
        homes = [p / "Contents" / "Home" for p in base.glob("*")] if base.is_dir() else []
        return homes + [Path("/Applications/Android Studio.app/Contents/jbr/Contents/Home")]
    out = []
    jvm = Path("/usr/lib/jvm")
    if jvm.is_dir():
        out += sorted(jvm.glob("*17*"), reverse=True)
    return out


def resolve_java_home() -> Path | None:
    """Resolve a JDK for avdmanager/sdkmanager (which require Java).

    JAVA_HOME env first (if it has a java binary), then conventional install
    locations including Android Studio's bundled JBR. Returns None if none found.
    """
    java_exe = "java.exe" if sys.platform == "win32" else "java"
    env = (os.environ.get("JAVA_HOME") or "").strip()
    candidates = ([Path(env)] if env else []) + _java_home_candidates()
    for c in candidates:
        try:
            if (c / "bin" / java_exe).is_file():
                return c.resolve()
        except Exception:
            continue
    return None


def tool_env() -> dict:
    """Environment for SDK subprocesses: ensures JAVA_HOME + ANDROID_SDK_ROOT are
    set (and java on PATH) regardless of how the parent shell was configured, so
    avdmanager/sdkmanager work without relying on global env propagation."""
    env = dict(os.environ)
    sdk = resolve_sdk_root()
    if sdk is not None:
        env["ANDROID_SDK_ROOT"] = str(sdk)
        env["ANDROID_HOME"] = str(sdk)
    jh = resolve_java_home()
    if jh is not None:
        env["JAVA_HOME"] = str(jh)
        sep = ";" if sys.platform == "win32" else ":"
        env["PATH"] = f"{jh / 'bin'}{sep}{env.get('PATH', '')}"
    return env


def get_profiles() -> dict:
    """All named AVD profiles from apps_config.yaml (or {})."""
    profs = _config_section().get("profiles")
    return profs if isinstance(profs, dict) else {}


def get_profile(name: str) -> dict | None:
    """One named profile, or None if it isn't defined."""
    return get_profiles().get(name)


def default_profile_name() -> str | None:
    """The configured default profile name, if any."""
    return _config_section().get("default_profile")


def merge_profile(name: str | None = None, overrides: dict | None = None) -> dict:
    """Resolve the effective AVD/launch config: profile defaults + per-call overrides.

    `name` None → use default_profile (if configured) → empty base. Override
    keys with a value of None are ignored so callers can pass a full kwargs dict
    without clobbering profile values. Raises KeyError if a non-default name is
    given but not defined (so typos surface instead of silently using defaults).
    """
    base: dict = {}
    chosen = name or default_profile_name()
    if chosen:
        prof = get_profile(chosen)
        if prof is None:
            if name:  # explicit, unknown name → loud
                raise KeyError(
                    f"AVD profile {name!r} not found. Defined: "
                    f"{sorted(get_profiles())}"
                )
        else:
            base = dict(prof)
    base["profile"] = chosen
    for k, v in (overrides or {}).items():
        if v is not None:
            base[k] = v
    return base
