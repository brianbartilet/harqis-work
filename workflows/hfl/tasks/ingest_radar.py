"""
workflows/hfl/tasks/ingest_radar.py

Daily DAILY RADAR briefings → HFL corpus. The DAILY RADAR HUD widget
(workflows/hud/tasks/hud_radar.py :: show_daily_radar) fires every few
hours and writes its synthesized briefing to the shared per-day desktop
feed file via the @feed() decorator. This task reads that day's radar
briefings back out, distils them into ONE Homework-for-Life entry, and
appends it to the corpus so the day's working context flows into
summarize_hfl_week + the memory_recall MCP.

Why read the feed instead of re-running the radar:
  - The radar is the EXPENSIVE producer — it pulls ~9 live sources (gmail,
    calendar, tasks, trello, jira, github, owntracks, failed jobs, desktop
    logs) and synthesizes with Sonnet, every few hours. Re-running it at
    ingest time would re-pull everything and generate a *new* briefing,
    not ingest the day's. Instead we read the briefings it already wrote.
  - Source of truth is the desktop feed file the radar writes to:
        <feed_dir>/<prefix>-YYYYMMDD.txt
    where `feed_dir` is resolved exactly as apps.desktop.helpers.feed does
    (DESKTOP_PATH_FEED_<OS> override → CONFIG["feed"]["path_to_feed"]), and
    `prefix` is the @feed() filename_prefix the radar uses ("hud-logs").
    That file is Google-Drive-synced, so the Beat host reads the briefings
    a Windows radar wrote. Every @feed() block is tagged
    `>> Start\\n<ts> :: <func_name>`; we keep only `show_daily_radar` blocks.

No feed dir configured / not an existing directory on this host → no
entry, no LLM call (clean no-op, mirrors ingest_git_activity on a quiet
day). No radar briefings in the window → no entry, no LLM call.

Distil with Claude Haiku only — never raise the Anthropic DEFAULT_MODEL
(the radar already paid for Sonnet; the daily rollup is cheap).

The collectors (collect_radar_activity / distill_radar_activity) are plain
functions so the MCP tool (workflows/hfl/mcp.py :: radar_activity) can
reuse them for a live, no-write view.
"""

from __future__ import annotations

import re
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Optional

from core.apps.sprout.app.celery import SPROUT
from core.apps.es_logging.app.elasticsearch import log_result
from core.utilities.logging.custom_logger import create_logger

from apps.antropic.config import get_config as get_anthropic_config
from apps.antropic.references.web.base_api_service import BaseApiServiceAnthropic
from apps.desktop.helpers.feed import _resolve_feed_path

from workflows.hfl.prompts import load_prompt
from workflows.hfl.tasks.capture import _build_entry, append_entry, resolve_corpus_dir
from workflows.hfl.tasks.ingest_git import _parse_model_json

_log = create_logger("hfl.ingest_radar")

_DEFAULT_HAIKU = "claude-haiku-4-5-20251001"

# The @feed() filename_prefix and the radar's task name. show_daily_radar is
# decorated with a bare @feed(), so it lands in the default "hud-logs" file
# alongside other HUD tasks; we filter to its own blocks by func name.
_DEFAULT_FEED_PREFIX = "hud-logs"
_RADAR_FUNC_NAME = "show_daily_radar"

# Matches each @feed() block header (apps/desktop/helpers/feed.py):
#   >> Start
#   2026-06-23 16:55:06 :: show_daily_radar
_BLOCK_HEADER = re.compile(
    r">> Start\s*\n\s*(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})\s*::\s*(\w+)\s*\n"
)


def _resolve_feed_dir() -> Optional[Path]:
    """The feed dir for THIS OS, or None when not an existing directory.

    Reuses apps.desktop.helpers.feed._resolve_feed_path so the path
    resolution (OS-specific override → config) is identical to the writer.
    Mirrors the writer's deliberate "don't create it" contract: a path
    shaped for another OS is just a non-existent dir here → no-op.
    """
    raw = _resolve_feed_path()
    if not raw or "${" in raw:
        return None
    d = Path(raw)
    if not d.is_dir():
        return None
    return d.resolve()


def _strip_footer(body: str) -> str:
    """Drop the trailing make_separator('>') line + blank padding a block
    carries before the next `>> Start` (or EOF)."""
    lines = body.splitlines()
    while lines and (not lines[-1].strip() or set(lines[-1].strip()) <= {">"}):
        lines.pop()
    return "\n".join(lines).strip()


def _parse_feed_briefings(
    text: str, *, since: date, until: date, func_name: str = _RADAR_FUNC_NAME
) -> list[dict[str, str]]:
    """Pull `func_name` blocks from one feed file's text, windowed by date.

    Blocks are prepended newest-first; we walk header matches in order and
    take each block's body up to the next header (or EOF).
    """
    out: list[dict[str, str]] = []
    matches = list(_BLOCK_HEADER.finditer(text))
    for i, m in enumerate(matches):
        ts_raw, fn = m.group(1), m.group(2)
        if fn != func_name:
            continue
        try:
            when = datetime.strptime(ts_raw, "%Y-%m-%d %H:%M:%S")
        except ValueError:
            continue
        if not (since <= when.date() <= until):
            continue
        body_start = m.end()
        body_end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        body = _strip_footer(text[body_start:body_end])
        if body:
            out.append({"when": when.strftime("%Y-%m-%d %H:%M"), "text": body})
    return out


def collect_radar_activity(
    *,
    since: date,
    until: date,
    feed_dir: Optional[Path] = None,
    prefix: str = _DEFAULT_FEED_PREFIX,
    func_name: str = _RADAR_FUNC_NAME,
    max_briefings: int = 24,
) -> dict[str, Any]:
    """Read the day's radar briefings from the desktop feed file(s).

    Walks one `<prefix>-YYYYMMDD.txt` per day in [since, until], parses the
    `func_name` @feed() blocks, and returns them oldest-first.

    Returns:
        {"briefings": [{"when","text"}], "briefing_count",
         "feed_files": [<path read that contributed>]}
        — feed_dir unresolved → all empty (caller treats as clean no-op).
    """
    feed_dir = feed_dir or _resolve_feed_dir()
    if feed_dir is None:
        return {"briefings": [], "briefing_count": 0, "feed_files": []}

    briefings: list[dict[str, str]] = []
    files_used: list[str] = []
    day = since
    while day <= until:
        fpath = feed_dir / f"{prefix}-{day.strftime('%Y%m%d')}.txt"
        day += timedelta(days=1)
        if not fpath.is_file():
            continue
        try:
            text = fpath.read_text(encoding="utf-8", errors="replace")
        except OSError as exc:  # noqa: PERF203 - a bad file shouldn't break the day
            _log.info("ingest_radar: could not read %s (%s)", fpath, exc)
            continue
        found = _parse_feed_briefings(
            text, since=since, until=until, func_name=func_name
        )
        if found:
            briefings.extend(found)
            files_used.append(str(fpath))

    briefings.sort(key=lambda b: b["when"])
    if len(briefings) > max_briefings:
        briefings = briefings[-max_briefings:]  # keep the most recent run-set

    return {
        "briefings": briefings,
        "briefing_count": len(briefings),
        "feed_files": files_used,
    }


def _activity_body(activity: dict) -> str:
    lines: list[str] = []
    for b in activity["briefings"]:
        lines.append(f"### Briefing @ {b['when']}")
        lines.append(b["text"])
    return "\n\n".join(lines)


def distill_radar_activity(
    activity: dict,
    *,
    synthesize: bool = True,
    model: str = _DEFAULT_HAIKU,
    cfg_id: str = "ANTHROPIC",
    max_tokens: int = 900,
) -> dict[str, Any]:
    """Turn the day's radar briefings into HFL entry fields (Haiku, raw fallback)."""
    count = activity["briefing_count"]

    def _fallback() -> dict:
        latest = activity["briefings"][-1]["text"] if activity["briefings"] else ""
        preview = latest.strip().splitlines()
        body = "\n".join(preview[:12]).strip()
        return {
            "skip": False,
            "moment": f"{count} DAILY RADAR briefing(s) over the day",
            "what_happened": body or f"{count} radar briefings captured.",
            "why_it_stayed": "",
            "possible_use": "retro",
            "tags": ["radar", "hud", "briefing"],
            "synthesized": False,
        }

    if not synthesize:
        return _fallback()

    user_msg = (
        f"Today's DAILY RADAR briefings ({count} run(s), newest last):\n\n"
        f"{_activity_body(activity)}"
    )
    try:
        client = BaseApiServiceAnthropic(get_anthropic_config(cfg_id))
        if not getattr(client, "base_client", None):
            _log.warning("ingest_radar: Anthropic not initialized — raw fallback")
            return _fallback()
        resp = client.send_message(
            prompt=user_msg,
            system=load_prompt("ingest_radar").strip(),
            model=model,
            max_tokens=max_tokens,
        )
        text = resp.content[0].text if resp and resp.content else ""
        parsed = _parse_model_json(text)
        if not parsed:
            return _fallback()
        parsed.setdefault("skip", False)
        for key in ("moment", "what_happened", "why_it_stayed", "possible_use"):
            parsed[key] = str(parsed.get(key, "")).strip()
        parsed["tags"] = [str(t).strip().lstrip("#") for t in (parsed.get("tags") or [])]
        parsed["synthesized"] = True
        return parsed
    except Exception as exc:  # noqa: BLE001 - never break the beat on API error
        _log.warning("ingest_radar: synthesis failed (%s) — raw fallback", exc)
        return _fallback()


@SPROUT.task()
@log_result()
def ingest_radar_activity(
    *,
    cfg_id__anthropic: str = "ANTHROPIC",
    model: str = _DEFAULT_HAIKU,
    window_days: int = 1,
    prefix: str = _DEFAULT_FEED_PREFIX,
    max_briefings: int = 24,
) -> dict[str, Any]:
    """Append one HFL corpus entry summarizing the day's DAILY RADAR briefings.

    No feed dir configured on this host → no entry, no network call.
    No radar briefings in the window → no entry, no LLM call.
    """
    feed_dir = _resolve_feed_dir()
    if feed_dir is None:
        _log.info("ingest_radar: no feed dir configured on this host — no-op")
        return {"skipped": "no feed dir", "entries_written": 0, "briefings": 0}

    until = datetime.now().date()
    since = until - timedelta(days=window_days)

    try:
        activity = collect_radar_activity(
            since=since, until=until, feed_dir=feed_dir,
            prefix=prefix, max_briefings=max_briefings,
        )
    except Exception as exc:  # noqa: BLE001 - feed read must not break beat
        _log.error("ingest_radar: feed read failed (%s)", exc)
        return {"skipped": "feed unreadable", "entries_written": 0,
                "error": str(exc)[:200]}

    if activity["briefing_count"] == 0:
        _log.info("ingest_radar: no radar briefings in last %d day(s)", window_days)
        return {"skipped": "no briefings", "entries_written": 0, "briefings": 0}

    d = distill_radar_activity(
        activity, synthesize=True, model=model,
        cfg_id=cfg_id__anthropic, max_tokens=900,
    )
    if d.get("skip"):
        _log.info("ingest_radar: distilled as skip — %d briefings not story-worthy",
                  activity["briefing_count"])
        return {"skipped": "distilled-skip", "entries_written": 0,
                "briefings": activity["briefing_count"]}

    tags = ["radar", "hud", "briefing"] + [
        str(t) for t in (d.get("tags") or []) if str(t).strip()
    ][:6]

    when = datetime.now()
    corpus_dir = resolve_corpus_dir()
    corpus_dir.mkdir(parents=True, exist_ok=True)
    day_file = corpus_dir / f"{when.strftime('%Y-%m-%d')}.md"
    entry = _build_entry(
        when=when,
        moment=d["moment"],
        what_happened=d["what_happened"],
        why_it_stayed=d["why_it_stayed"],
        possible_use=d["possible_use"] or "retro",
        tags=tags,
        references=activity["feed_files"],  # provenance: the feed file(s) read
    )
    _bytes, doc_id = append_entry(
        day_file, entry,
        source="radar", synthesized=d.get("synthesized", False),
    )

    _log.info("ingest_radar: entry written (%d briefings) -> %s",
              activity["briefing_count"], day_file)
    return {
        "entries_written": 1,
        "briefings": activity["briefing_count"],
        "indexed": doc_id is not None,
        "synthesized": d.get("synthesized", False),
        "model": model if d.get("synthesized") else None,
        "path": str(day_file),
    }
