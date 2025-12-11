import functools
import json
import os
import time
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Any, Mapping

from apps.desktop.config import CONFIG
from core.utilities.data.strings import make_separator
from core.utilities.logging.custom_logger import logger as log


def _atomic_write_text(
    path: Path,
    text: str,
    encoding: str = "utf-8",
    prepend_if_exists: bool = False,
) -> None:
    """
    Atomically write text to `path`.

    - Default: overwrite existing file.
    - If `prepend_if_exists=True` and file exists, new text is written
      BEFORE the existing contents (prepend).
    """
    path.parent.mkdir(parents=True, exist_ok=True)

    if prepend_if_exists and path.exists():
        try:
            existing = path.read_text(encoding=encoding)
        except UnicodeDecodeError:
            # Fallback if encoding is weird – just best-effort decode
            existing = path.read_bytes().decode(encoding, errors="ignore")
        text_to_write = text + existing
    else:
        text_to_write = text

    with tempfile.NamedTemporaryFile(
        "w",
        delete=False,
        dir=str(path.parent),
        encoding=encoding,
    ) as tmp:
        tmp.write(text_to_write)
        tmp_path = Path(tmp.name)

    os.replace(tmp_path, path)  # atomic on Windows


def _prepend_with_lock(
    path: Path,
    block_text: str,
    encoding: str = "utf-8",
    lock_timeout_secs: int | None = None,
    lock_sleep_secs: float = 0.1,
    stale_lock_max_age_secs: float | None = 300.0,  # 5 minutes default
) -> None:
    """
    Prepend `block_text` to `path` in a process-safe way using a lock file.

    - Creates `<path>.lock` as a mutual exclusion primitive.
    - Waits (with optional timeout) if another process is writing.
    - Optionally treats very old locks as "stale" and removes them.
    - Uses `_atomic_write_text` to ensure the final write is atomic.
    """
    lock_path = path.with_suffix(path.suffix + ".lock")
    start = time.time()

    # Acquire lock (spin until available)
    while True:
        try:
            # Try to create the lock file exclusively
            fd = os.open(str(lock_path), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            os.close(fd)
            break  # lock acquired
        except FileExistsError:
            # Check for stale lock (too old -> remove and retry)
            if stale_lock_max_age_secs is not None and lock_path.exists():
                try:
                    mtime = lock_path.stat().st_mtime
                    age = time.time() - mtime
                    if age > stale_lock_max_age_secs:
                        # Stale lock; remove and retry acquiring
                        try:
                            os.remove(lock_path)
                            continue  # go back and try to acquire again
                        except FileNotFoundError:
                            # Someone else removed it; just loop again
                            continue
                except FileNotFoundError:
                    # Lock disappeared between exists() and stat(); loop again
                    continue

            # Regular timeout handling
            if lock_timeout_secs is not None and (time.time() - start) > lock_timeout_secs:
                raise TimeoutError(f"Timed out waiting for lock on {path}")

            time.sleep(lock_sleep_secs)

    try:
        # Read existing content (if any)
        if path.exists():
            try:
                existing = path.read_text(encoding=encoding)
            except UnicodeDecodeError:
                existing = path.read_bytes().decode(encoding, errors="ignore")
        else:
            existing = ""

        new_text = block_text + existing
        _atomic_write_text(path, new_text, encoding=encoding)
    finally:
        # Best-effort lock cleanup
        try:
            os.remove(lock_path)
        except FileNotFoundError:
            pass


def _safe_stringify(obj: Any) -> str:
    """
    Convert ANY Python object to a clean string representation.
    Priority:
        1) str(obj) if safe
        2) JSON pretty-print if serializable
        3) repr(obj) as fallback
    Ensures returned value is always a valid string.
    """
    # None -> ""
    if obj is None:
        return ""

    # Already a string
    if isinstance(obj, str):
        return obj

    # Bytes -> decode best effort
    if isinstance(obj, bytes):
        try:
            return obj.decode("utf-8", errors="replace")
        except Exception:
            return repr(obj)

    # Try JSON (for dicts, lists, dataclasses, simple objects)
    try:
        return json.dumps(obj, indent=2, default=str)
    except Exception:
        pass

    # Fallback: repr
    try:
        return str(obj)
    except Exception:
        return repr(obj)


def feed(filename_prefix: str = "hud-logs",
         encoding: str = "utf-8",
         lock_timeout_secs: int | None = None):
    """
    Decorator: captures ANY returned value from the wrapped function,
    converts it to a safe string, and prepends it into a per-day master file.

    - File: <write_skin_to_feed>/RainmeterFeeds/<prefix>-YYYYMMDD.txt
    - Prepends newest data at top
    - Uses file lock to prevent concurrency corruption
    - Returns original returned value converted to string
    """
    try:
        root = Path(CONFIG["feed"]["path_to_feed"]).resolve()
        feed_dir = root
        feed_dir.mkdir(parents=True, exist_ok=True)
    except FileNotFoundError:
        log.warn("The location for the feed is unavailable.  Skipping this entry.")

        return None

    def decorator(func):
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            # Call target function
            raw_result = func(*args, **kwargs)

            # Normalize ANY return type to a clean string
            dump = _safe_stringify(raw_result).rstrip()

            # Build per-day feed file
            day = datetime.now().strftime("%Y%m%d")
            feed_path = feed_dir / f"{filename_prefix}-{day}.txt"

            # Build header block
            timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            header = f">> Start\n{timestamp} :: {func.__name__}\n"
            footer = f"\n{make_separator(48, '>')}"
            block = f"{header}{dump}\n\n{footer}\n\n"

            # Prepend with locking
            _prepend_with_lock(
                path=feed_path,
                block_text=block,
                encoding=encoding,
                lock_timeout_secs=lock_timeout_secs,
            )

            # Return the stringified dump to next decorator (init_meter)
            return dump

        return wrapper

    return decorator
