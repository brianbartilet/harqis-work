"""
workflows/dumps/tasks/analyze.py

Daily analyzer: walks the inbox for one or more days, then pushes a per-machine
summary line to the HUD feed so the operator sees the result on the same
surface they already scan. It also APPENDS each day's Markdown summary block to
a single consolidated <dir>/daily-dumps.log in the repo + Drive-synced sinks —
see workflows/dumps/summary_store.py. The feed/ES paths are untouched; the log
is additive (same shape as HFL keeping both a corpus and an ES projection).

Default (no kwargs) analyzes *yesterday* — the once-a-day batch. It also
accepts a retro window so missed days can be summarized after the fact:

    analyze_daily_dumps()                          # yesterday (default)
    analyze_daily_dumps(days=7)                    # last 7 full days
    analyze_daily_dumps(date="2026-06-12")         # one specific day
    analyze_daily_dumps(start="2026-05-01", end="2026-05-31")
    analyze_daily_dumps(month="2026-05")           # whole calendar month

Retro only sees days whose `<machine>-daily-dumps-<date>` folders still exist
in the inbox; a missed day simply renders as "0 machines (no dumps)", which is
exactly the gap signal you want. Must run on harqis-server (host-guard below) —
the inbox physically lives there.

This is the Express path the manifesto requires of every Capture task —
see docs/MANIFESTO.md §1 ("Build a second brain") and
docs/thesis/MANIFESTO-REPO-UPDATES.md §4.5.

The Trello / kanban-agent hand-off remains a follow-up enhancement; the
marker stays as `# FUTURE: kanban agent hand-off` below.
"""
from __future__ import annotations

import calendar
from datetime import datetime, timedelta
from pathlib import Path

from core.apps.sprout.app.celery import SPROUT
from core.apps.es_logging.app.elasticsearch import log_result
from core.utilities.logging.custom_logger import create_logger

from apps.desktop.helpers.feed import feed
from workflows.dumps.config import (
    HARQIS_SERVER_MACHINE_NAME,
    get_dumps_target,
    resolve_local_machine_name,
)
from workflows.dumps.files import parse_dump_dir_name, previous_day_window
from workflows.dumps.summary_store import append_day_summary, render_day_markdown

_log = create_logger("dumps.analyze")


def _resolve_target_dates(
    *,
    days: int | None = None,
    date: str | None = None,
    start: str | None = None,
    end: str | None = None,
    month: str | None = None,
    now: datetime | None = None,
) -> list[str]:
    """Resolve the kwargs into a sorted list of 'YYYY-MM-DD' day-strings.

    Precedence (first match wins): date → start/end → month → days → default.
    Ranges are capped at *yesterday*: today's folder is still being filled by
    the intra-day collect, and future days don't exist. An explicit `date` is
    NOT capped — if you ask for a specific day you get it verbatim.
    """
    now = now or datetime.now()
    today = datetime(now.year, now.month, now.day)
    yesterday = today - timedelta(days=1)

    def fmt(dt: datetime) -> str:
        return dt.strftime("%Y-%m-%d")

    def span(a: datetime, b: datetime) -> list[str]:
        out, cur = [], a
        while cur <= b:
            out.append(fmt(cur))
            cur += timedelta(days=1)
        return out

    if date:
        return [date]
    if start or end:
        s = datetime.strptime(start, "%Y-%m-%d") if start else yesterday
        e = datetime.strptime(end, "%Y-%m-%d") if end else yesterday
        if s > e:
            s, e = e, s
        e = min(e, yesterday)
        return span(s, e) if s <= e else []
    if month:
        y, m = (int(x) for x in str(month).split("-")[:2])
        first = datetime(y, m, 1)
        last = min(datetime(y, m, calendar.monthrange(y, m)[1]), yesterday)
        return span(first, last) if first <= last else []
    if days:
        n = max(1, int(days))
        return span(yesterday - timedelta(days=n - 1), yesterday)
    return [fmt(yesterday)]


def _scan_day(inbox: Path, date_suffix: str) -> list[dict]:
    """Return the per-machine dump stats for a single day in the inbox."""
    machines: list[dict] = []
    for entry in sorted(inbox.iterdir()):
        if not entry.is_dir():
            continue
        parsed = parse_dump_dir_name(entry.name)
        if parsed is None or parsed[1] != date_suffix:
            continue
        machine_name = parsed[0]
        files = [p for p in entry.rglob("*") if p.is_file()]
        size = sum(p.stat().st_size for p in files if p.exists())
        machines.append({
            "machine": machine_name,
            "files_count": len(files),
            "bytes_total": size,
            "path": str(entry),
        })
        _log.info("dumps: %s - %d files (%d bytes) at %s",
                  machine_name, len(files), size, entry)
    return machines


def _filter_machines(machines: list[dict], machine: str | None = None) -> list[dict]:
    """Limit scanned dump stats to one machine/device name when requested."""
    if not machine:
        return machines
    return [m for m in machines if m.get("machine") == machine]


def _human_bytes(n: int) -> str:
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if n < 1024 or unit == "TB":
            return f"{n:.1f} {unit}" if unit != "B" else f"{n} B"
        n /= 1024
    return f"{n:.1f} PB"


def _render_summary(date_suffix: str, machines: list[dict], inbox_path: str) -> str:
    """Human-readable summary that lands on the HUD feed."""
    if not machines:
        return (
            f"Daily dumps - {date_suffix} - no machine dumps found at {inbox_path}.\n"
        )

    files_total = sum(m["files_count"] for m in machines)
    bytes_total = sum(m["bytes_total"] for m in machines)
    by_bytes = sorted(machines, key=lambda m: m["bytes_total"], reverse=True)
    top = by_bytes[0]

    lines = [
        f"Daily dumps - {date_suffix} - {len(machines)} machine(s) - "
        f"{files_total} files - {_human_bytes(bytes_total)}",
        f"  top by bytes: {top['machine']} ({_human_bytes(top['bytes_total'])})",
    ]
    for m in by_bytes[:5]:
        lines.append(
            f"  - {m['machine']}: {m['files_count']} files, "
            f"{_human_bytes(m['bytes_total'])}"
        )
    if len(by_bytes) > 5:
        lines.append(f"  - ... and {len(by_bytes) - 5} more")
    return "\n".join(lines) + "\n"


def _render_multi(dates: list[str], per_day: dict[str, list[dict]],
                  inbox_path: str) -> str:
    """Per-day breakdown + grand total for a retro (multi-day) run."""
    days_with = [d for d in dates if per_day.get(d)]
    files_total = sum(m["files_count"] for d in dates for m in per_day.get(d, []))
    bytes_total = sum(m["bytes_total"] for d in dates for m in per_day.get(d, []))

    lines = [f"Daily dumps retro - {dates[0]}..{dates[-1]} - {len(dates)} day(s)"]
    for d in dates:
        ms = per_day.get(d, [])
        if not ms:
            lines.append(f"  {d}: 0 machines (no dumps)")
            continue
        fc = sum(m["files_count"] for m in ms)
        bt = sum(m["bytes_total"] for m in ms)
        lines.append(f"  {d}: {len(ms)} machine(s), {fc} files, {_human_bytes(bt)}")
    lines.append(
        f"  TOTAL: {files_total} files, {_human_bytes(bytes_total)} across "
        f"{len(days_with)}/{len(dates)} day(s) with dumps"
    )
    if not days_with:
        lines.append(f"  (no machine dumps found in range at {inbox_path})")
    return "\n".join(lines) + "\n"


def _render_gaps(dates: list[str], gap_dates: list[str]) -> str:
    """Gaps-only view: list just the days with no dumps (the 'what did I miss?')."""
    total = len(dates)
    span = f"{dates[0]}..{dates[-1]}" if total > 1 else dates[0]
    if not gap_dates:
        return f"Daily dumps gaps - {span} - none; all {total} day(s) have dumps.\n"
    lines = [f"Daily dumps gaps - {span} - {len(gap_dates)} of {total} day(s) missing:"]
    lines.extend(f"  {d}: no dumps" for d in gap_dates)
    lines.append(f"  ({total - len(gap_dates)}/{total} day(s) had dumps)")
    return "\n".join(lines) + "\n"


@SPROUT.task(name="workflows.dumps.tasks.analyze_daily_dumps")
@log_result()
@feed()
def analyze_daily_dumps(**kwargs) -> dict:
    """Inspect one or more days of dumps and push a summary to the HUD feed.

    Kwargs (all optional; see module docstring for precedence):
        days, date, start, end, month — retro window. None ⇒ yesterday.
        machine — optional exact machine/device folder prefix filter.
        missing_only — render only the days with NO dumps (gap report) instead
                       of the full per-day breakdown.
        write_md — append the day's Markdown block to daily-dumps.log (default
                   True). Pass False to render the feed/ES summary only.
    """
    # Host-guard: the inbox (harqis_server_inbox, e.g. /Volumes/harqis-data/dumps)
    # physically lives on harqis-server only. The `host` queue is meant to be
    # consumed by harqis-server alone, but if another box ever subscribes to it
    # a competing-consumers race would run this here and evaluate a path that
    # doesn't exist locally -> a bogus "inbox not yet created" summary that also
    # starves the real run (one consumer per message). Self-defend regardless of
    # queue topology drift: only the canonical hub analyzes; everyone else no-ops.
    local_machine = resolve_local_machine_name()
    if local_machine != HARQIS_SERVER_MACHINE_NAME:
        _log.info("dumps: analyze skipped on %s - not harqis-server (%s); the "
                  "inbox lives on the hub only.",
                  local_machine, HARQIS_SERVER_MACHINE_NAME)
        return {"text": "", "skipped": True, "machine": local_machine}

    target = get_dumps_target()
    if not target:
        _log.error("dumps: [dumps] harqis_server_inbox missing - cannot analyze")
        return {"text": "Daily dumps - error: harqis_server_inbox not set\n",
                "error": "harqis_server_inbox not set"}

    dates = _resolve_target_dates(
        days=kwargs.get("days"),
        date=kwargs.get("date"),
        start=kwargs.get("start"),
        end=kwargs.get("end"),
        month=kwargs.get("month"),
    )
    if not dates:
        _log.warning("dumps: analyze - kwargs %s resolved to an empty date range",
                     {k: kwargs.get(k) for k in ("days", "date", "start", "end", "month")})
        return {"text": "Daily dumps - error: empty date range\n",
                "error": "empty date range"}

    inbox = Path(target.inbox).expanduser()

    if not inbox.exists():
        _log.info("dumps: inbox %s does not exist yet", inbox)
        empty_text = f"Daily dumps - {dates[0]} - inbox {inbox} not yet created.\n"
        return {"text": empty_text, "date": dates[0], "machines": 0}

    machine_filter = kwargs.get("machine")
    per_day = {d: _filter_machines(_scan_day(inbox, d), machine_filter) for d in dates}
    missing_only = bool(kwargs.get("missing_only"))
    write_md = bool(kwargs.get("write_md", True))

    # ─────────────────────────────────────────────────────────────────────────
    # FUTURE: kanban agent hand-off (optional enhancement)
    # The HUD-feed summary above closes the manifesto's "captures must
    # express" rule. A richer downstream is still possible:
    #   1. Build a Trello card per machine (or per day) with:
    #        - Title: "Daily dumps - <machine> - <YYYY-MM-DD>"
    #        - Description: file counts, byte totals, path
    #        - Label:  agent:write (or whichever profile owns the analysis)
    #   2. The kanban orchestrator will pick the card up, the agent will
    #      walk the dump tree, and post a summary back as a comment.
    # Keep that invocation in the kanban path so quotas, persona, and audit
    # all funnel through one place.
    # ─────────────────────────────────────────────────────────────────────────

    # Gaps-only view: report just the days with no dumps (works for any window).
    if missing_only:
        gap_dates = [d for d in dates if not per_day.get(d)]
        summary_text = _render_gaps(dates, gap_dates)
        _log.info("dumps: analyze gaps - %d/%d day(s) missing for %s..%s, "
                  "summary pushed to HUD feed.",
                  len(gap_dates), len(dates), dates[0], dates[-1])
        return {
            "text": summary_text,
            "start": dates[0],
            "end": dates[-1],
            "days": len(dates),
            "days_missing": len(gap_dates),
            "gaps": gap_dates,
        }

    # Consolidated Markdown log sink (workflows/dumps/summary_store.py):
    # APPENDS each day-with-dumps block to a single <dir>/daily-dumps.log, in
    # both the repo sink and the Drive-synced feed sink. Additive — the HUD feed
    # (@feed) and ES (@log_result) paths above are untouched. A gap day appends
    # nothing: its absence IS the signal, and `missing_only` already reports
    # gaps. Best-effort per sink, so a failure never breaks the analyze run. The
    # same per-day Markdown blocks are also returned as `markdown` for the caller
    # to print (the retro runner's md output).
    summary_files: list[str] = []
    markdown_blocks: list[str] = []
    if write_md:
        for d in dates:
            ms = per_day.get(d) or []
            if ms:
                markdown_blocks.append(render_day_markdown(d, ms, str(inbox)).rstrip())
                summary_files.extend(append_day_summary(d, ms, str(inbox)))
    # One daily-dumps.log per sink → de-dupe the repeated paths across days.
    summary_files = sorted(set(summary_files))
    markdown = "\n\n".join(markdown_blocks)

    # Single-day → legacy shape (the daily Beat run relies on this). Multi-day
    # → per-day breakdown + grand total.
    if len(dates) == 1:
        date_suffix = dates[0]
        machines = per_day[date_suffix]
        summary_text = _render_summary(date_suffix, machines, str(inbox))
        _log.info("dumps: analyze finished - %d machine dump(s) for %s, summary "
                  "pushed to HUD feed.", len(machines), date_suffix)
        return {
            "text": summary_text,
            "date": date_suffix,
            "machines": len(machines),
            "files_total": sum(m["files_count"] for m in machines),
            "bytes_total": sum(m["bytes_total"] for m in machines),
            "details": machines,
            "summary_files": summary_files,
            "markdown": markdown,
        }

    summary_text = _render_multi(dates, per_day, str(inbox))
    days_with = [d for d in dates if per_day.get(d)]
    _log.info("dumps: analyze retro finished - %d/%d day(s) with dumps for "
              "%s..%s, summary pushed to HUD feed.",
              len(days_with), len(dates), dates[0], dates[-1])
    return {
        "text": summary_text,
        "start": dates[0],
        "end": dates[-1],
        "days": len(dates),
        "days_with_dumps": len(days_with),
        "files_total": sum(m["files_count"] for d in dates for m in per_day[d]),
        "bytes_total": sum(m["bytes_total"] for d in dates for m in per_day[d]),
        "by_day": {d: per_day[d] for d in dates},
        "summary_files": summary_files,
        "markdown": markdown,
    }
