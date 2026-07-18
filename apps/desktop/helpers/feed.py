import functools
import hashlib
import json
import os
import sys
import tempfile
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Optional, TypeVar

from apps.desktop.config import CONFIG
from core.utilities.data.strings import make_separator
from core.utilities.logging.custom_logger import logger as log

T = TypeVar("T")


# -----------------------------
# Configuration / Defaults
# -----------------------------

DEFAULT_ENCODING = "utf-8"
DEFAULT_LOCK_DIRNAME = "feed-locks"          # stored under %TEMP%
DEFAULT_LOCK_SLEEP_SECS = 0.1
DEFAULT_STALE_LOCK_MAX_AGE_SECS = 300.0      # 5 minutes

# Per-OS feed-path override env var. One shared .env/apps.env (or, once
# GH#11 lands, a machines.local.toml [<machine>.env_vars] block) can carry
# a path for every host; the running OS picks its own:
#
#   DESKTOP_PATH_FEED_DARWIN   -> macOS  (e.g. ~/Library/CloudStorage/...)
#   DESKTOP_PATH_FEED_WINDOWS  -> Windows (e.g. G:\My Drive\LOGS)
#   DESKTOP_PATH_FEED_LINUX    -> Linux
#
# The OS-specific var wins when set; otherwise we fall back to the
# OS-agnostic CONFIG["feed"]["path_to_feed"] (${DESKTOP_PATH_FEED}).
_OS_FEED_KEY = {"darwin": "DARWIN", "win32": "WINDOWS"}.get(sys.platform, "LINUX")
_OS_FEED_ENV = f"DESKTOP_PATH_FEED_{_OS_FEED_KEY}"


def _resolve_feed_path() -> str:
    """Pick the feed dir for *this* OS.

    Order: OS-specific override env var → OS-agnostic config value.
    Returns the raw (unresolved) string, or "" when nothing is configured.
    """
    os_specific = (os.environ.get(_OS_FEED_ENV) or "").strip()
    if os_specific:
        return os_specific
    return ((CONFIG.get("feed") or {}).get("path_to_feed") or "").strip()


@dataclass(frozen=True)
class FeedLockConfig:
    """
    Lock behavior config for feed file writes.

    Notes:
    - lock files live in a local temp directory to avoid Google Drive locking/sync issues.
    - stale locks are treated as best-effort removable; PermissionError is ignored and we wait.
    """
    lock_timeout_secs: Optional[int] = None
    lock_sleep_secs: float = DEFAULT_LOCK_SLEEP_SECS
    stale_lock_max_age_secs: Optional[float] = DEFAULT_STALE_LOCK_MAX_AGE_SECS
    lock_dir: Optional[Path] = None


# -----------------------------
# Helpers
# -----------------------------

def _ensure_dir(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)


def _lock_path_for(target_path: Path, *, lock_dir: Optional[Path] = None) -> Path:
    """
    Create a stable, filesystem-safe lock filename for the given target file path.

    We intentionally store lock files in %TEMP% (or provided lock_dir) so Google Drive
    sync won't hold/deny-delete the lock file, which is common on Windows.
    """
    if lock_dir is None:
        lock_dir = Path(tempfile.gettempdir()) / DEFAULT_LOCK_DIRNAME
    _ensure_dir(lock_dir)

    key = str(target_path.resolve()).encode(DEFAULT_ENCODING, errors="ignore")
    digest = hashlib.sha1(key).hexdigest()
    return lock_dir / f"{digest}.lock"


def _read_text_best_effort(path: Path, *, encoding: str) -> str:
    """
    Read text from file with encoding fallback.
    """
    try:
        return path.read_text(encoding=encoding)
    except UnicodeDecodeError:
        return path.read_bytes().decode(encoding, errors="ignore")


def _atomic_write_text(
    path: Path,
    text: str,
    *,
    encoding: str = DEFAULT_ENCODING,
    prepend_if_exists: bool = False,
) -> None:
    """
    Atomically write text to `path`.

    - Default: overwrite existing file.
    - If `prepend_if_exists=True` and file exists, new text is written BEFORE the existing contents.
    """
    _ensure_dir(path.parent)

    if prepend_if_exists and path.exists():
        existing = _read_text_best_effort(path, encoding=encoding)
        text_to_write = text + existing
    else:
        text_to_write = text

    with tempfile.NamedTemporaryFile(
        mode="w",
        delete=False,
        dir=str(path.parent),
        encoding=encoding,
    ) as tmp:
        tmp.write(text_to_write)
        tmp_path = Path(tmp.name)

    os.replace(tmp_path, path)


def _acquire_lock(lock_path: Path, cfg: FeedLockConfig, *, target_path: Path) -> None:
    """
    Spin until we can create the lock file exclusively.
    Handles stale locks and Windows PermissionError gracefully.
    """
    start = time.time()

    while True:
        try:
            fd = os.open(str(lock_path), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            try:
                # Debug metadata can help when diagnosing "stuck" locks
                os.write(
                    fd,
                    f"pid={os.getpid()} time={time.time()} target={target_path}\n".encode(
                        DEFAULT_ENCODING, errors="ignore"
                    ),
                )
            finally:
                os.close(fd)
            return  # acquired

        except FileExistsError:
            # Stale lock handling
            if cfg.stale_lock_max_age_secs is not None and lock_path.exists():
                try:
                    age = time.time() - lock_path.stat().st_mtime
                    if age > cfg.stale_lock_max_age_secs:
                        try:
                            os.remove(lock_path)
                            continue
                        except FileNotFoundError:
                            continue
                        except PermissionError:
                            # Windows/Drive sync might hold the file briefly; do not crash.
                            pass
                except FileNotFoundError:
                    continue

            # Timeout handling
            if cfg.lock_timeout_secs is not None and (time.time() - start) > cfg.lock_timeout_secs:
                raise TimeoutError(f"Timed out waiting for lock on {target_path}")

            time.sleep(cfg.lock_sleep_secs)


def _release_lock(lock_path: Path) -> None:
    """
    Best-effort lock cleanup. On Windows a lock file can be temporarily undeletable.
    """
    try:
        os.remove(lock_path)
    except (FileNotFoundError, PermissionError):
        pass


def _prepend_with_lock(
    *,
    path: Path,
    block_text: str,
    encoding: str = DEFAULT_ENCODING,
    lock_cfg: Optional[FeedLockConfig] = None,
) -> None:
    """
    Prepend `block_text` to `path` using a temp-based lock file for process safety.

    - Lock file stored in %TEMP% to avoid Google Drive / sync lock contention.
    - Stale lock cleanup is best-effort; PermissionError never crashes the task.
    - Final write uses atomic replace.
    """
    cfg = lock_cfg or FeedLockConfig()
    lock_path = _lock_path_for(path, lock_dir=cfg.lock_dir)

    _acquire_lock(lock_path, cfg, target_path=path)
    try:
        existing = _read_text_best_effort(path, encoding=encoding) if path.exists() else ""
        _atomic_write_text(path, block_text + existing, encoding=encoding)
    finally:
        _release_lock(lock_path)


def _safe_stringify(obj: Any) -> str:
    """
    Convert ANY Python object to a clean string representation.
    Priority:
        1) string as-is
        2) bytes -> utf-8 decode best-effort
        3) JSON pretty-print if serializable
        4) str(obj) fallback
        5) repr(obj) final fallback
    """
    if obj is None:
        return ""

    if isinstance(obj, str):
        return obj

    if isinstance(obj, bytes):
        try:
            return obj.decode(DEFAULT_ENCODING, errors="replace")
        except Exception:
            return repr(obj)

    try:
        return json.dumps(obj, indent=2, default=str)
    except Exception:
        pass

    try:
        return str(obj)
    except Exception:
        return repr(obj)


# -----------------------------
# Public decorator
# -----------------------------

def _extract_dump_text(raw_result: Any) -> str:
    """Pull the human-readable dump out of a task return value.

    HUD tasks may return either a string (legacy: just the dump text) or a
    dict shaped like ``{"text": "<dump>", "summary": ..., "metrics": ...}``.
    A task may provide ``feed_text`` when its shared feed must intentionally
    differ from the rendered HUD text (for example, HERMES RADAR keeps the
    legacy synthesis feed separate from its four-hour Telegram mirror). The feed file
    never receives the JSON metadata.
    """
    if isinstance(raw_result, dict) and "feed_text" in raw_result:
        text = raw_result.get("feed_text", "")
        return text if isinstance(text, str) else _safe_stringify(text)
    if isinstance(raw_result, dict) and "text" in raw_result:
        text = raw_result.get("text", "")
        return text if isinstance(text, str) else _safe_stringify(text)
    return _safe_stringify(raw_result)


def feed(
    filename_prefix: str = "hud-logs",
    *,
    encoding: str = DEFAULT_ENCODING,
    lock_timeout_secs: int | None = None,
    lock_sleep_secs: float = DEFAULT_LOCK_SLEEP_SECS,
    stale_lock_max_age_secs: float | None = DEFAULT_STALE_LOCK_MAX_AGE_SECS,
) -> Callable[[Callable[..., T]], Callable[..., Any]]:
    """
    Decorator: capture ANY return value from wrapped func, write its dump
    text into a per-day feed file, then return the *original* value
    untouched so outer decorators (e.g. ``@init_meter``) can still inspect
    structured returns like ``{"text", "summary", "metrics"}``.

    - File: <CONFIG["feed"]["path_to_feed"]>/<prefix>-YYYYMMDD.txt
    - Prepends newest data at top
    - Uses temp-based lock to prevent concurrent corruption (safe for GDrive logs)
    - Returns the wrapped function's value as-is (string OR dict)
    """
    def _noop_decorator(func: Callable[..., T]) -> Callable[..., Any]:
        @functools.wraps(func)
        def wrapper(*args, **kwargs) -> Any:
            return func(*args, **kwargs)
        return wrapper

    raw_feed_path = _resolve_feed_path()
    if not raw_feed_path or "${" in raw_feed_path:
        log.warning(
            "Feed path not configured (%s / DESKTOP_PATH_FEED); @feed is a "
            "no-op.", _OS_FEED_ENV,
        )
        return _noop_decorator

    # The directory MUST already exist on this OS. We deliberately do NOT
    # create it: a path shaped for a different OS (e.g. Windows
    # ``G:\My Drive\LOGS`` on a POSIX worker) is just a non-existent
    # relative path here — Path.is_dir() is False and we skip cleanly
    # WITHOUT resolve()+mkdir, so no junk directory is ever created in the
    # cwd. Same skip path covers an unmounted drive, a typo, or a host
    # that simply has no feed sink. Note: don't .resolve() before this
    # check — resolve() would rebase a foreign relative path onto cwd.
    feed_dir = Path(raw_feed_path)
    if not feed_dir.is_dir():
        log.warning(
            "Feed path %r is not an existing directory on this host "
            "(platform=%s); @feed is a no-op. Create the directory or set "
            "%s to a valid path for this OS.",
            raw_feed_path, sys.platform, _OS_FEED_ENV,
        )
        return _noop_decorator
    feed_dir = feed_dir.resolve()

    lock_cfg = FeedLockConfig(
        lock_timeout_secs=lock_timeout_secs,
        lock_sleep_secs=lock_sleep_secs,
        stale_lock_max_age_secs=stale_lock_max_age_secs,
        lock_dir=None,  # keep lock files in %TEMP% by default
    )

    def decorator(func: Callable[..., T]) -> Callable[..., Any]:
        @functools.wraps(func)
        def wrapper(*args, **kwargs) -> Any:
            raw_result = func(*args, **kwargs)
            dump = _extract_dump_text(raw_result).rstrip()

            day = datetime.now().strftime("%Y%m%d")
            feed_path = feed_dir / f"{filename_prefix}-{day}.txt"

            timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            header = f">> Start\n{timestamp} :: {func.__name__}\n"
            footer = f"\n{make_separator(48, '>')}"
            block = f"{header}{dump}\n\n{footer}\n\n"

            try:
                _prepend_with_lock(
                    path=feed_path,
                    block_text=block,
                    encoding=encoding,
                    lock_cfg=lock_cfg,
                )
            except Exception as exc:
                log.warning(
                    "Feed write skipped for %s: %s. Returning wrapped result unchanged.",
                    feed_path,
                    exc,
                )

            return raw_result

        return wrapper

    return decorator
