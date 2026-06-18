"""
workflows/dumps/tasks/analyze.py

Daily analyzer: walks the previous day's inbox, then pushes a per-machine
summary line to the HUD feed so the operator sees the result on the same
surface they already scan.

This is the Express path the manifesto requires of every Capture task —
see docs/MANIFESTO.md §1 ("Build a second brain") and
docs/thesis/MANIFESTO-REPO-UPDATES.md §4.5.

The Trello / kanban-agent hand-off remains a follow-up enhancement; the
marker stays as `# FUTURE: kanban agent hand-off` below.
"""
from __future__ import annotations

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
from workflows.dumps.files import previous_day_window

_log = create_logger("dumps.analyze")


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


@SPROUT.task(name="workflows.dumps.tasks.analyze_daily_dumps")
@log_result()
@feed()
def analyze_daily_dumps(**kwargs) -> dict:
    """Inspect the previous day's dumps and push a summary to the HUD feed."""
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

    inbox = Path(target.inbox).expanduser()
    start, _ = previous_day_window()
    date_suffix = start.strftime("%Y-%m-%d")

    if not inbox.exists():
        _log.info("dumps: inbox %s does not exist yet", inbox)
        empty_text = f"Daily dumps - {date_suffix} - inbox {inbox} not yet created.\n"
        return {"text": empty_text, "date": date_suffix, "machines": 0}

    machines: list[dict] = []
    for entry in sorted(inbox.iterdir()):
        if not entry.is_dir() or not entry.name.endswith(f"-daily-dumps-{date_suffix}"):
            continue
        machine_name = entry.name[: -len(f"-daily-dumps-{date_suffix}")]
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

    summary_text = _render_summary(date_suffix, machines, str(inbox))

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

    _log.info("dumps: analyze finished - %d machine dump(s) for %s, summary "
              "pushed to HUD feed.", len(machines), date_suffix)
    return {
        "text": summary_text,
        "date": date_suffix,
        "machines": len(machines),
        "files_total": sum(m["files_count"] for m in machines),
        "bytes_total": sum(m["bytes_total"] for m in machines),
        "details": machines,
    }
