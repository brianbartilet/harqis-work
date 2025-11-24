from __future__ import annotations


from apps.google_apps.references.constants import ScheduleCategory

import functools
import hashlib
import os
import tempfile
import winsound
import time
import ctypes

from .bangs import _refresh_app, _activate_config, _deactivate_config

user32 = ctypes.windll.user32
WM_COPYDATA = 0x004A

from configparser import ConfigParser
from pathlib import Path
from typing import Callable, Dict, Iterable, Mapping, Optional, List

from core.utilities.logging.custom_logger import logger as log

from apps.google_apps.references.web.api.calendar import ApiServiceGoogleCalendarEvents, EventType
from apps.apps_config import CONFIG_MANAGER

WAIT_SECS_DEFAULT = 10
BEEP_FREQUENCY = 1200
BEEP_DURATION_MS = 300


def init_meter(
    config: Mapping[str, str],
    hud_item_name: str,
    template_name: str = "base.ini",
    include_notes_bin: bool = True,
    notes_file: str = "dump.txt",
    new_sections_dict: Optional[Dict[str, Dict[str, str]]] = None,
    reset_alerts_secs: int = 10,
    play_sound: bool = True,
    always_alert: bool = False,
    schedule_categories: List[ScheduleCategory] = None
) -> Callable:
    """
    Decorator: prepares Rainmeter skin dirs, renders an INI from a template,
    writes notes, toggles border color on change, beeps, activates & refreshes,
    waits a bit, then resets the border.

    Required config keys:
      - skin_name: str
      - static_path: str (folder containing @Resources, Options, template INIs, bin/LuaTextFile.lua)
      - write_skin_to_path: str (Rainmeter Skins root, e.g. ~/Documents/Rainmeter/Skins)
      - bin_path: str (path to Rainmeter.exe)
    """

    # --- Validate required config early
    required = ("skin_name", "static_path", "write_skin_to_path", "bin_path")
    missing = [k for k in required if k not in config or not config[k]]
    if missing:
        raise ValueError(f"Missing required config keys: {', '.join(missing)}")

    skin_name = config["skin_name"]
    static_path = Path(config["static_path"]).resolve()
    skins_root = Path(config["write_skin_to_path"]).resolve()
    rainmeter_exe = Path(config["bin_path"]).resolve()

    skin_dir = skins_root / skin_name
    hud_dirname = sanitize_name(hud_item_name)  # safer than only stripping spaces
    ini_dir = skin_dir / hud_dirname
    ini_filename = f"{hud_dirname}.ini"
    ini_path = ini_dir / ini_filename
    note_path = ini_dir / notes_file
    template_path = static_path / template_name

    def decorator(func: Callable) -> Callable:
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            try:
                # 1) Ensure skin folder structure/resources exist
                _ensure_dirs_and_resources(
                    static_path=static_path,
                    skin_dir=skin_dir,
                    ini_dir=ini_dir,
                    include_notes_bin=include_notes_bin,
                )
                # 2) Load template config
                cfg = ConfigHelperRainmeter(template_config_file=str(template_path))
                cfg.read_template_configuration()

                # 3) Add optional sections/keys
                if new_sections_dict:
                    for sect, kv in new_sections_dict.items():
                        if not cfg.has_section(sect):
                            cfg.add_section(sect)
                        for k, v in (kv or {}).items():
                            cfg.set(sect, k, v)

                # 4) Let user function compute the notes text
                notes_text: str = func(ini=cfg, *args, **kwargs)
                if not isinstance(notes_text, str):
                    notes_text = str(notes_text)

                # 5) Detect change vs. existing notes
                changed = always_alert or _content_changed(note_path, notes_text)

                # 6) Write notes atomically
                _atomic_write_text(note_path, notes_text, encoding="utf-8")

                # 7) Update displayed title safely
                set_config_value(cfg, "meterTitle", "text", hud_item_name)

                # 8) Flip border color in the INI if changed
                border_from = "Stroke Color [#darkColor]"
                border_to = "Stroke Color [#alertColor]" if changed else "Stroke Color [#warnColor]"
                replace_ini_value(cfg, "MeterBackground", "shape", border_from, border_to)

                # 9) Save INI atomically
                cfg.save_to_new_file(str(ini_path))

                # 10) Process schedule categories if and break process
                if schedule_categories:
                    if ScheduleCategory.PINNED in schedule_categories:
                        log.info("ScheduleCategory.PINNED found; keeping HUD active.")
                    else:
                        google_cfg_id = kwargs.get("calendar_cfg_id", None)
                        if not google_cfg_id:
                            raise ValueError("'calendar_cfg_id' is required in kwargs when schedule_categories is set")
                        config_calendar = CONFIG_MANAGER.get(google_cfg_id)
                        service = ApiServiceGoogleCalendarEvents(config_calendar)
                        now_blocks = service.get_all_events_today(EventType.NOW)
                        matches = any([c.value in {b['calendarSummary'] for b in now_blocks} for c in schedule_categories])
                        if matches:
                            pass
                        else:
                            log.warn("No matching schedule categories found; deactivating HUD until next check.")
                            _deactivate_config(skin_name, hud_dirname)
                            return {"updated": changed, "ini_path": str(ini_path), "notes_path": note_path}

                # 11) Optional beep
                if changed and play_sound:
                    try:
                        winsound.Beep(BEEP_FREQUENCY, BEEP_DURATION_MS)
                    except RuntimeError:
                        pass  # ignore if no sound device

                # 12) Activate & refresh Rainmeter
                _activate_config(skin_name, hud_dirname, ini_filename)
                _refresh_app()

                # 13) Reset border after wait
                time.sleep(reset_alerts_secs if changed else WAIT_SECS_DEFAULT)
                cfg_reset = ConfigHelperRainmeter(template_config_file=str(ini_path))
                cfg_reset.read_template_configuration()
                replace_ini_value(cfg_reset, "MeterBackground", "shape", border_to, "Stroke Color [#darkColor]")
                cfg_reset.save_to_new_file(str(ini_path))

                _activate_config(skin_name, hud_dirname, ini_filename)
                _refresh_app()

                # Return useful info for callers/tests
                return {"updated": changed, "ini_path": str(ini_path), "notes_path": str(note_path)}

            except Exception as e:
                log.error(f"Failed HUD initialization: {e}")
                raise e

        return wrapper

    return decorator


# ----------------------
# Helpers
# ----------------------

def sanitize_name(name: str) -> str:
    """Make a filesystem-friendly short name."""
    import re
    # Keep alnum, space, hyphen, underscore; replace others with underscore; then remove spaces.
    cleaned = re.sub(r"[^A-Za-z0-9 _-]+", "_", name)
    return cleaned.replace(" ", "")


def _ensure_dirs_and_resources(
    static_path: Path, skin_dir: Path, ini_dir: Path, include_notes_bin: bool
) -> None:
    skin_dir.mkdir(parents=True, exist_ok=True)
    ini_dir.mkdir(parents=True, exist_ok=True)

    # Copy @Resources and Options (idempotent)
    _copytree(static_path / "@Resources", skin_dir / "@Resources")
    _copytree(static_path / "Options", skin_dir / "Options")

    if include_notes_bin:
        bin_dir = static_path / "bin"
        if bin_dir.exists():
            # Copy ALL .lua files from bin → ini_dir
            for src in bin_dir.glob("*.lua"):
                dst = ini_dir / src.name
                if not dst.exists() or src.stat().st_mtime > dst.stat().st_mtime:
                    dst.write_bytes(src.read_bytes())


def _copytree(src: Path, dst: Path) -> None:
    if not src.exists():
        return
    # Python ≥3.8
    import shutil
    shutil.copytree(src, dst, dirs_exist_ok=True)


def _content_changed(path: Path, new_text: str, encoding: str = "utf-8") -> bool:
    if not path.exists():
        return True
    try:
        old = path.read_text(encoding=encoding)
    except UnicodeDecodeError:
        # Fallback to bytes comparison if encoding differs
        return _hash_bytes(path.read_bytes()) != _hash_bytes(new_text.encode(encoding))
    return old != new_text


def _hash_bytes(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def _atomic_write_text(path: Path, text: str, encoding: str = "utf-8") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", delete=False, dir=str(path.parent), encoding=encoding) as tmp:
        tmp.write(text)
        tmp_path = Path(tmp.name)
    os.replace(tmp_path, path)  # atomic on Windows




def set_config_value(cfg: ConfigParser, section: str, key: str, value: str) -> None:
    if not cfg.has_section(section):
        cfg.add_section(section)
    cfg.set(section, key, value)


def replace_ini_value(cfg: ConfigParser, section: str, key: str, old: str, new: str) -> None:
    """
    Replaces substring `old` → `new` for a given key in a section if present.
    No-op if section/key missing.
    """
    if cfg.has_section(section) and cfg.has_option(section, key):
        cfg.set(section, key, cfg.get(section, key).replace(old, new))


class ConfigHelperRainmeter(ConfigParser):
    def __init__(self, template_config_file: Optional[str] = None):
        super().__init__()
        self.template_config_file = template_config_file

    def read(self, filenames: Iterable[str] | str, encoding: Optional[str] = "utf-8"):
        super().read(filenames=filenames, encoding=encoding)

    def read_template_configuration(self):
        if not self.template_config_file:
            raise ValueError("template_config_file is not set")
        return self.read(self.template_config_file)

    def save_to_new_file(self, ini_file_name: str, encoding: str = "utf-8") -> None:
        # Atomic write
        path = Path(ini_file_name)
        with tempfile.NamedTemporaryFile("w", delete=False, dir=str(path.parent), encoding=encoding) as tmp:
            self.write(tmp)
            tmp_path = Path(tmp.name)
        os.replace(tmp_path, path)


class NotesTextHelperRainmeter:
    def __init__(self, file_name_txt: str):
        self.file_name_txt = Path(file_name_txt)

    def write(self, stream: str, encoding: str = "utf-8") -> None:
        _atomic_write_text(self.file_name_txt, stream, encoding=encoding)
