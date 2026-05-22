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


def collect_window(
    window_days: int = 1,
    include_today: bool = False,
    now: datetime | None = None,
) -> tuple[datetime, datetime]:
    """Return (start, end) naive local-time bounds for a collect run.

    Args:
        window_days:   how many calendar days the window spans (>= 1).
        include_today: when True the window extends through *now* (so files
                       edited today are in scope); when False it stops at
                       today 00:00 (the classic "previous full day(s)" batch).
        now:           override the clock (testing).

    Examples (window_days=1):
        include_today=False → [yesterday 00:00, today 00:00)   ← daily batch
        include_today=True  → [today 00:00,     now]           ← same-day catch-up
    """
    now = now or datetime.now()
    days = max(1, int(window_days))
    today_midnight = datetime(now.year, now.month, now.day)
    if include_today:
        end = now
        start = today_midnight - timedelta(days=days - 1)
    else:
        end = today_midnight
        start = today_midnight - timedelta(days=days)
    return start, end


def previous_day_window(now: datetime | None = None) -> tuple[datetime, datetime]:
    """Return (start, end) for the local previous calendar day — i.e.
    `collect_window(window_days=1, include_today=False)`. Kept for callers
    that want the classic once-a-day batch window."""
    return collect_window(window_days=1, include_today=False, now=now)


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
