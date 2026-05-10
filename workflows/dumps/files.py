"""
workflows/dumps/files.py

File walking + previous-day filtering. Cross-platform via pathlib.

A "previous day" window is `[yesterday 00:00:00, today 00:00:00)` in the
machine's local timezone. Files are matched on their `mtime` (modification
time). On Windows that also covers creation, on POSIX it covers
content modification (close enough for log/screenshot use cases).
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Iterator


def previous_day_window(now: datetime | None = None) -> tuple[datetime, datetime]:
    """Return (start, end) datetimes for the local previous calendar day.

    Both bounds are timezone-naive local-time `datetime` objects.
    `start` is yesterday 00:00:00, `end` is today 00:00:00 (exclusive).
    """
    now = now or datetime.now()
    today_midnight = datetime(now.year, now.month, now.day)
    yesterday_midnight = today_midnight - timedelta(days=1)
    return yesterday_midnight, today_midnight


@dataclass(frozen=True)
class CollectedFile:
    """A single file matched by `iter_recent_files`.

    Attributes:
        source_root: The configured root path under which this file lives.
        path:        Absolute path to the actual file on disk.
        relative:    Path of `path` relative to `source_root` (preserves the
                     internal directory structure for archive layout).
        mtime:       File modification time as a naive local datetime.
    """
    source_root: Path
    path: Path
    relative: Path
    mtime: datetime


def iter_recent_files(
    source_roots: list[str | Path],
    start: datetime,
    end: datetime,
) -> Iterator[CollectedFile]:
    """Walk every source root and yield files with mtime in `[start, end)`.

    Silently skips:
    - Source roots that don't exist.
    - Files we can't `stat()` (permission errors, race deletions).
    - Symlinks pointing outside their source root (avoid escape).
    """
    start_ts = start.timestamp()
    end_ts = end.timestamp()
    for root_str in source_roots:
        root = Path(root_str).expanduser()
        if not root.exists() or not root.is_dir():
            continue
        try:
            root_resolved = root.resolve()
        except OSError:
            continue
        for p in root.rglob("*"):
            try:
                if not p.is_file():
                    continue
                # Symlink-escape guard: resolved path must stay under the root.
                resolved = p.resolve()
                try:
                    resolved.relative_to(root_resolved)
                except ValueError:
                    continue
                stat = p.stat()
                if start_ts <= stat.st_mtime < end_ts:
                    yield CollectedFile(
                        source_root=root,
                        path=p,
                        relative=p.relative_to(root),
                        mtime=datetime.fromtimestamp(stat.st_mtime),
                    )
            except (OSError, PermissionError):
                continue


def group_by_source(files: list[CollectedFile]) -> dict[Path, list[CollectedFile]]:
    """Bucket collected files by their source root.

    Used by the broadcast task to ship each source root as one tar stream
    with paths preserved relative to that root.
    """
    out: dict[Path, list[CollectedFile]] = {}
    for f in files:
        out.setdefault(f.source_root, []).append(f)
    return out


def format_dump_dir_name(machine_name: str, day: datetime) -> str:
    """Produce `<machine>-daily-dumps-YYYY-MM-DD` for the given local day."""
    return f"{machine_name}-daily-dumps-{day.strftime('%Y-%m-%d')}"
