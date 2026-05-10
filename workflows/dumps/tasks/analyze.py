"""
workflows/dumps/tasks/analyze.py

Placeholder — this is where the daily-dumps analyzer agent will be wired in
later. Today it just logs the inbox contents for the previous day so you can
verify the broadcast/pull tasks landed the files correctly.

TODO: hand off to a kanban agent profile (likely `agent:write` or a new
`agent:analyze`) that reads the dump tree, summarises desktop activity,
groups screenshots/pictures by inferred event, and posts results to Trello
as a card per-day or per-machine. The hand-off point is marked `# AGENT
WIRE-UP HERE` below.
"""
from __future__ import annotations

from pathlib import Path

from core.apps.sprout.app.celery import SPROUT
from core.apps.es_logging.app.elasticsearch import log_result
from core.utilities.logging.custom_logger import create_logger

from workflows.dumps.config import get_dumps_target
from workflows.dumps.files import previous_day_window

_log = create_logger("dumps.analyze")


@SPROUT.task(name="workflows.dumps.tasks.analyze_daily_dumps")
@log_result()
def analyze_daily_dumps(**kwargs) -> dict:
    """Inspect the previous day's dumps and (eventually) hand off to an agent."""
    target = get_dumps_target()
    if not target:
        _log.error("dumps: [dumps] harqis_server_inbox missing — cannot analyze")
        return {"error": "harqis_server_inbox not set"}

    inbox = Path(target.inbox).expanduser()
    start, _ = previous_day_window()
    date_suffix = start.strftime("%Y-%m-%d")

    if not inbox.exists():
        _log.info("dumps: inbox %s does not exist yet", inbox)
        return {"date": date_suffix, "machines": 0, "todo": "agent not yet wired"}

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
        _log.info("dumps: %s — %d files (%d bytes) at %s",
                  machine_name, len(files), size, entry)

    # ─────────────────────────────────────────────────────────────────────────
    # AGENT WIRE-UP HERE
    # When the analyzer agent is ready:
    #   1. Build a Trello card per machine (or per day) with:
    #        - Title: "Daily dumps — <machine> — <YYYY-MM-DD>"
    #        - Description: file counts, byte totals, path
    #        - Label:  agent:write (or whichever profile owns the analysis)
    #        - Custom field `system_prompt_addon`: any per-machine context
    #   2. The kanban orchestrator will pick the card up, the agent will
    #      walk the dump tree (read_file / glob / grep), and post a summary
    #      back as a comment.
    # No code calls Claude from this task directly — keep the agent
    # invocation in the kanban path so quotas, persona, and audit all funnel
    # through one place.
    # ─────────────────────────────────────────────────────────────────────────

    _log.info("dumps: analyze placeholder finished — %d machine dump(s) for %s. "
              "TODO: hand off to agent.", len(machines), date_suffix)
    return {
        "date": date_suffix,
        "machines": len(machines),
        "details": machines,
        "todo": "agent not yet wired — see AGENT WIRE-UP HERE in analyze.py",
    }
