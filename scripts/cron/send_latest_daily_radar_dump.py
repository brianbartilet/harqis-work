#!/usr/bin/env python3
"""Extract the latest HARQIS Daily Radar dump from Google Drive LOGS.

Intended for Hermes no-agent cron delivery to Telegram.

The Daily Radar can land in either:
- hud-logs-YYYYMMDD.txt when the normal HUD job ran
- hud-data-only-YYYYMMDD.txt when the data-only follow-up ran

This script scans both families and forwards the newest radar section found.
"""
from __future__ import annotations

import datetime as dt
import re
import signal
import time
from dataclasses import dataclass
from pathlib import Path

LOGS_DIR = Path("/Users/harqis-one/Library/CloudStorage/GoogleDrive-brian.bartilet@gmail.com/My Drive/LOGS")
FILE_RE = re.compile(r"^hud-(?:logs|data-only)-(\d{8})\.txt$")
START_RE = re.compile(
    r"^(?P<ts>\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}) :: show_daily_radar(?:_data_only)?\s*$",
    re.MULTILINE,
)
NEXT_SECTION_RE = re.compile(r"^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2} :: ", re.MULTILINE)
DELIM_RE = re.compile(r"^>{20,}\s*$", re.MULTILINE)


@dataclass(frozen=True)
class RadarSection:
    path: Path
    file_date: str
    file_mtime: float
    section_ts: dt.datetime
    text: str


def candidate_files() -> list[Path]:
    if not LOGS_DIR.exists():
        return []
    candidates: list[tuple[str, float, Path]] = []
    for path in LOGS_DIR.iterdir():
        if not path.is_file():
            continue
        match = FILE_RE.match(path.name)
        if not match:
            continue
        try:
            mtime = path.stat().st_mtime
        except OSError:
            mtime = 0
        candidates.append((match.group(1), mtime, path))
    # Most recent dates first, but keep all files so fallback works when today's
    # normal hud log exists without a radar section.
    return [path for _, _, path in sorted(candidates, key=lambda item: (item[0], item[1]), reverse=True)]


def section_end(text: str, start_end: int) -> int:
    after = text[start_end:]
    ends: list[int] = []
    delim = DELIM_RE.search(after)
    if delim:
        ends.append(start_end + delim.start())
    next_section = NEXT_SECTION_RE.search(after)
    if next_section:
        ends.append(start_end + next_section.start())
    return min(ends) if ends else len(text)


def read_log_text(path: Path, attempts: int = 3, timeout_seconds: int = 3) -> tuple[str, float] | None:
    """Read a Google Drive log file with retries and a timeout for provider locks."""

    def on_timeout(signum, frame):  # type: ignore[no-untyped-def]
        raise TimeoutError(f"Timed out reading {path}")

    previous_handler = signal.getsignal(signal.SIGALRM)
    for attempt in range(attempts):
        try:
            signal.signal(signal.SIGALRM, on_timeout)
            signal.alarm(timeout_seconds)
            try:
                text = path.read_text(encoding="utf-8", errors="replace")
                mtime = path.stat().st_mtime
            finally:
                signal.alarm(0)
                signal.signal(signal.SIGALRM, previous_handler)
            return text, mtime
        except (OSError, TimeoutError):
            signal.alarm(0)
            signal.signal(signal.SIGALRM, previous_handler)
            if attempt == attempts - 1:
                return None
            time.sleep(0.25 * (attempt + 1))
    return None


def extract_sections(path: Path) -> list[RadarSection]:
    read_result = read_log_text(path)
    if read_result is None:
        return []
    raw, file_mtime = read_result

    file_match = FILE_RE.match(path.name)
    file_date = file_match.group(1) if file_match else "00000000"
    sections: list[RadarSection] = []

    for match in START_RE.finditer(raw):
        try:
            section_ts = dt.datetime.strptime(match.group("ts"), "%Y-%m-%d %H:%M:%S")
        except ValueError:
            section_ts = dt.datetime.fromtimestamp(file_mtime)
        text = raw[match.start() : section_end(raw, match.end())].strip()
        if text:
            sections.append(
                RadarSection(
                    path=path,
                    file_date=file_date,
                    file_mtime=file_mtime,
                    section_ts=section_ts,
                    text=text,
                )
            )
    return sections


def latest_radar_section() -> RadarSection | None:
    sections: list[RadarSection] = []
    # Scan only the freshest files. This avoids old Google Drive placeholders or
    # locked CloudStorage files from delaying the cron, while still allowing a
    # same-day data-only fallback and a recent previous-day fallback.
    for path in candidate_files()[:10]:
        sections.extend(extract_sections(path))
    if not sections:
        return None
    return max(sections, key=lambda s: (s.section_ts, s.file_date, s.file_mtime, s.path.name))


def main() -> int:
    now = dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S %Z")
    files = candidate_files()
    if not files:
        print(f"DAILY RADAR LOG FORWARDER — {now}\nNo hud-logs/hud-data-only YYYYMMDD.txt files found in {LOGS_DIR}")
        return 0

    section = latest_radar_section()
    if section is None:
        inspected = "\n".join(str(path) for path in files[:5])
        print(
            f"DAILY RADAR LOG FORWARDER — {now}\n"
            "No show_daily_radar or show_daily_radar_data_only section found in latest LOGS files.\n"
            f"Inspected:\n{inspected}"
        )
        return 0

    print(f"DAILY RADAR DUMP\nSource: {section.path}\nForwarded: {now}\n")
    print(section.text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
