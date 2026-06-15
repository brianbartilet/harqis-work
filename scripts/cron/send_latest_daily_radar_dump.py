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
import os
import re
import signal
import subprocess
import sys
import textwrap
import time
from dataclasses import dataclass
from pathlib import Path

# Paths come from the environment so nothing host-specific (user dir, cloud
# account) ships in the public source. The Google Drive LOGS mount is OS-correct:
# DESKTOP_PATH_FEED_DARWIN on macOS (this cron's host), else DESKTOP_PATH_FEED —
# same convention as workflows/desktop feed.py. Set these in .env/apps.env.
_feed = (os.environ.get("DESKTOP_PATH_FEED_DARWIN") if sys.platform == "darwin" else None) \
    or os.environ.get("DESKTOP_PATH_FEED", "/path/to/GoogleDrive/My Drive/LOGS")
LOGS_DIR = Path(_feed)
HARQIS_REPO = Path(os.environ.get("ENV_ROOT") or Path(__file__).resolve().parents[2])
FILE_RE = re.compile(r"^hud-(?:logs|data-only)-(\d{8})\.txt$")
START_RE = re.compile(
    r"^(?P<ts>\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}) :: show_daily_radar(?:_data_only)?\s*$",
    re.MULTILINE,
)
NEXT_SECTION_RE = re.compile(r"^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2} :: ", re.MULTILINE)
DELIM_RE = re.compile(r"^>{20,}\s*$", re.MULTILINE)
WIDE_RULE_RE = re.compile(r"^[=>\-_*]{24,}\s*$", re.MULTILINE)
BOX_TITLE_RE = re.compile(r"━{8,}\s*(?P<title>[^━\n]+?)\s*━{8,}")
SUGGESTED_RE = re.compile(
    r"SUGGESTED FIRST MOVE\s*\n[=\-_*]{8,}\s*\n(?P<move>.*?)(?=\n\[END\]|\Z)",
    re.IGNORECASE | re.DOTALL,
)
END_RE = re.compile(r"^\[END\]\s+(?P<end>\d{4}-\d{2}-\d{2}\s+\d{2}:\d{2})\s*$", re.MULTILINE)
SECTION_HEADER_RE = re.compile(r"^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2} :: show_daily_radar(?:_data_only)?\s*$", re.MULTILINE)
USER_ID_RE = re.compile(r"\b([uUhH]\d{5}|u\d{5}|H\d{5})\b")
ACTIVATION_RE = re.compile(r"(activation\s+code\s*)(?:[\"'(]?[A-Z0-9]{3,10}[\"') ]?)", re.IGNORECASE)
SEPARATOR = "━━━━━━━━━━━━━━━━━━━━"


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
                return read_log_text_via_drive_api(path)
            time.sleep(0.25 * (attempt + 1))
    return None


def _drive_file_id_from_xattr(path: Path) -> str | None:
    try:
        result = subprocess.run(
            ["xattr", "-p", "com.google.drivefs.item-id#S", str(path)],
            check=False,
            capture_output=True,
            text=True,
            timeout=2,
        )
    except Exception:
        return None
    file_id = result.stdout.strip()
    return file_id or None


def read_log_text_via_drive_api(path: Path) -> tuple[str, float] | None:
    """Bypass macOS FileProvider deadlocks by downloading via Drive API."""
    python = HARQIS_REPO / ".venv" / "bin" / "python"
    if not python.exists():
        return None
    file_id = _drive_file_id_from_xattr(path) or ""
    code = r'''
import contextlib
import io
import sys
from pathlib import Path

repo = Path(sys.argv[1])
file_name = sys.argv[2]
file_id = sys.argv[3] or None
sys.path.insert(0, str(repo))

# HARQIS imports emit operational logs on stdout. Keep stdout clean so the
# parent receives only file bytes.
with contextlib.redirect_stdout(sys.stderr):
    from scripts.launch import setup_env
    setup_env()
    from apps.apps_config import CONFIG_MANAGER
    from apps.google_apps.references.web.api.drive import ApiServiceGoogleDrive
    service = ApiServiceGoogleDrive(CONFIG_MANAGER.get("GOOGLE_DRIVE"))
    if not file_id:
        matches = service.list_files(
            query=f"name='{file_name}' and trashed=false",
            page_size=1,
            fields="files(id,name,mimeType,size,modifiedTime)",
        )
        if not matches:
            raise SystemExit(2)
        file_id = matches[0]["id"]
    raw = service.download_file(file_id)

sys.stdout.buffer.write(raw)
'''
    try:
        result = subprocess.run(
            [str(python), "-c", code, str(HARQIS_REPO), path.name, file_id],
            cwd=str(HARQIS_REPO),
            check=False,
            capture_output=True,
            timeout=30,
        )
        if result.returncode != 0 or not result.stdout:
            return None
        return result.stdout.decode("utf-8", errors="replace"), path.stat().st_mtime
    except Exception:
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


def redact_sensitive(text: str) -> str:
    """Keep the Telegram digest useful without leaking raw operational IDs."""
    text = ACTIVATION_RE.sub(r"\1[redacted]", text)
    text = USER_ID_RE.sub("[user-id]", text)
    return text


def extract_suggested_move(text: str) -> tuple[str | None, str]:
    match = SUGGESTED_RE.search(text)
    if not match:
        return None, text
    move = " ".join(match.group("move").strip().split())
    without = text[: match.start()] + text[match.end() :]
    return redact_sensitive(move), without


def extract_end_time(text: str) -> tuple[str | None, str]:
    match = END_RE.search(text)
    if not match:
        return None, text
    without = text[: match.start()] + text[match.end() :]
    return match.group("end"), without


def normalize_heading(text: str) -> str:
    return " ".join(text.strip().split()).title()


def parse_radar_sections(text: str) -> dict[str, list[str]]:
    """Parse the dump's native headings/bullets instead of re-wrapping it as prose."""
    text = SECTION_HEADER_RE.sub("", text)
    text = re.sub(r"^\[START\]\s+.*$", "", text, flags=re.MULTILINE)
    text = WIDE_RULE_RE.sub("", text)
    text = re.sub(r"━{8,}", "", text)
    text = text.replace("[END]", "")
    text = redact_sensitive(text)

    sections: dict[str, list[str]] = {}
    current_heading: str | None = None
    current_item: str | None = None

    def flush_item() -> None:
        nonlocal current_item
        if current_heading and current_item:
            sections.setdefault(current_heading, []).append(" ".join(current_item.split()))
        current_item = None

    for raw_line in text.splitlines():
        line = raw_line.rstrip()
        stripped = line.strip()
        if not stripped:
            flush_item()
            continue
        if stripped.upper().startswith("DAILY RADAR"):
            continue
        is_heading = (
            stripped == stripped.upper()
            and not stripped.startswith("-")
            and len(stripped) > 3
            and any(ch.isalpha() for ch in stripped)
        )
        if is_heading:
            flush_item()
            current_heading = normalize_heading(stripped)
            sections.setdefault(current_heading, [])
            continue
        if stripped.startswith("- "):
            flush_item()
            current_item = stripped[2:].strip()
            if current_heading is None:
                current_heading = "Timeline"
                sections.setdefault(current_heading, [])
            continue
        if current_item:
            current_item += " " + stripped
        elif current_heading:
            sections.setdefault(current_heading, []).append(stripped)
    flush_item()
    return {heading: items for heading, items in sections.items() if items}


def wrap_bullet(text: str, width: int = 74) -> list[str]:
    wrapped = textwrap.wrap(text, width=width, break_long_words=False, break_on_hyphens=False)
    if not wrapped:
        return []
    return ["- " + wrapped[0], *("  " + line for line in wrapped[1:])]


def append_section(lines: list[str], title: str, items: list[str], limit: int | None = None) -> None:
    if not items:
        return
    lines.append("")
    lines.append(f"**{title}**")
    chosen = items[:limit] if limit else items
    for item in chosen:
        lines.extend(wrap_bullet(item))
    if limit and len(items) > limit:
        lines.append(f"- …{len(items) - limit} more")


def compact_email_items(items: list[str]) -> list[str]:
    important = [item for item in items if item.startswith("[P0]") or item.startswith("[P1]")]
    p2_count = sum(1 for item in items if item.startswith("[P2]"))
    if p2_count:
        important.append(f"[P2] {p2_count} lower-priority digests/promos/job alerts demoted")
    return important


def render_mobile_digest(section: RadarSection, forwarded_at: str) -> str:
    raw = section.text.strip()
    suggested, remainder = extract_suggested_move(raw)
    end_time, remainder = extract_end_time(remainder)
    sections = parse_radar_sections(remainder)

    section_time = section.section_ts.strftime("%Y-%m-%d · %H:%M SGT")
    lines = [
        "**Daily Radar Dump**",
        f"`{section_time}`",
        "",
        "**First move**",
        suggested or "No concrete first move found in the dump.",
        "",
        SEPARATOR,
        "**Focus**",
    ]

    append_section(lines, "Top 3 priorities", sections.get("Top 3 Priorities Next 4 Hours", []))
    append_section(lines, "Overlooked commitments", sections.get("Overlooked Commitments", []))
    append_section(lines, "Email priority", compact_email_items(sections.get("Email Priority (Last 8H)", [])))
    append_section(lines, "Jira recent updates", sections.get("Jira Recent Updates (Last 8H)", []), limit=5)

    append_section(lines, "Signals / context", sections.get("Notification Triage", []), limit=4)

    if len(lines) <= 8:
        lines.append("- No timeline body found after post-processing.")

    lines.extend(
        [
            "",
            SEPARATOR,
            "**Privacy note**",
            "User IDs / activation codes are redacted in Telegram.",
            "",
            "**Source**",
            f"`{section.path.name}`",
            f"Forwarded: `{forwarded_at}`" + (f" · dump ended `{end_time} SGT`" if end_time else ""),
        ]
    )
    return "\n".join(lines).strip()


def main() -> int:
    now = dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S") + " SGT"
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

    print(render_mobile_digest(section, now))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
