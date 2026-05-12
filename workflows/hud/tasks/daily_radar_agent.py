"""
DAILY RADAR data-gathering helpers.

Combines five productivity ideas (AGENTS_IDEAS.md #1, #3, #4, #12, #17)
into a single 8-hour briefing fed to the daily_radar prompt:

  #1  Desktop Context Assistant   — tail of DESKTOP LOGS dump.txt
  #3  Overlooked Commitment       — Gmail body + desktop log scan
  #4  Email Priority              — Gmail recent emails (8h)
  #12 Notification Triage         — ES failed jobs + Trello + calendar
  #17 Daily Command Center        — Calendar today + Google Tasks open

Every collector is wrapped in a try/except so a single failing source
never breaks the HUD render — instead its section receives a small
"<source> unavailable: <reason>" payload and the prompt is told to skip
gracefully.

The output of `collect_inputs(...)` is a `dict` shaped for direct
inclusion in the Claude user-turn content blocks (`type=text`).
"""

from __future__ import annotations

import os
import re
import textwrap
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Dict, List, Optional

from core.utilities.logging.custom_logger import logger as log


# Window every collector queries. Kept in one place so the HUD task and
# the prompt header stay in sync.
ANALYSIS_WINDOW_HOURS: int = 8


# ---------------------------------------------------------------------------
# Source registry — declarative entries for every data feed the radar can
# pull from. The orchestration trio (collect_inputs / format_inputs_as_prompt_text
# / summarise_inputs) walks this registry instead of carrying per-source
# branches, so adding a new source is one entry — see hud README for the
# step-by-step.
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class SourceSpec:
    """One row in `SOURCE_REGISTRY`. Names a collector + formatter pair and
    pins them to a default config id.

    Attributes:
      name:           Lookup key. Appears in `sources=[...]` and in
                      `source_overrides` / `source_params` maps.
      default_cfg:    apps_config.yaml key to pass as `cfg_id` to the
                      collector. `None` for sources that don't read
                      `CONFIG_MANAGER` (e.g. ES failed-jobs, which reads
                      its own env). Overridable per-tick via
                      `source_overrides`.
      collector:      Callable with signature `(cfg_id, hours, **params)
                      -> {data, error}`. MUST be fail-soft — return the
                      error string, never raise.
      formatter:      Callable that takes the collector's output dict
                      and returns the text block for the LLM prompt.
                      MUST handle `error`, empty, and populated cases.
      payload_key:    Key under which the collector's output is stored
                      in the aggregated payload dict.
      prompt_marker:  UPPERCASE header the LLM expects above this
                      section in the prompt input. Must match the
                      section the daily_radar.md prompt asks for.
      count_field:    Optional list-field name inside the collector
                      output that `summarise_inputs` counts. None
                      sources don't emit a count.
      default_params: Default kwargs passed to the collector on every
                      call. Merged with (and overridden by)
                      `source_params[name]` at call time.
    """

    name: str
    default_cfg: Optional[str]
    collector: Callable[..., Dict[str, Any]]
    formatter: Callable[[Dict[str, Any]], str]
    payload_key: str
    prompt_marker: str
    count_field: Optional[str] = None
    default_params: Dict[str, Any] = field(default_factory=dict)


# Populated by `_register_default_sources()` at the bottom of this module
# AFTER every collector + formatter has been defined. Kept mutable so
# callers (or external modules) can register additional sources at import
# time without forking this file.
SOURCE_REGISTRY: Dict[str, SourceSpec] = {}


# Default priority list — the order the radar pulls and renders sources
# when the beat schedule doesn't pass an explicit `sources=[...]`. Order
# IS meaningful: the first entry's section appears first in the prompt
# input (and tends to weigh more in the LLM's synthesis).
DEFAULT_SOURCES: List[str] = [
    "gmail",
    "calendar",
    "gtasks",
    "trello",
    "jira",
    "github",
    "owntracks",
    "es_failed_jobs",
]

# Tail of DESKTOP LOGS dump.txt to feed back into the radar. dump.txt is
# capped at ~3 MB by hud_gpt._trim_dump_file; we read only the most-recent
# slice so the prompt stays under Anthropic's payload limits.
_DESKTOP_DUMP_TAIL_BYTES: int = 32 * 1024  # 32 KB ≈ last few ticks


# ---------------------------------------------------------------------------
# Desktop activity (idea #1) — read the dump.txt produced by get_desktop_logs
# ---------------------------------------------------------------------------

def read_desktop_dump_tail(dump_path: str,
                          tail_bytes: int = _DESKTOP_DUMP_TAIL_BYTES) -> str:
    """Return the last `tail_bytes` of `dump_path` as text.

    `get_desktop_logs` prepends new entries, so "tail" by file position is
    actually the OLDEST content. We read the HEAD instead — that's what the
    user sees on top of the HUD and what carries the most recent context.

    Returns an empty string when the file is missing.
    """
    if not dump_path or not os.path.exists(dump_path):
        return ""
    try:
        with open(dump_path, "rb") as f:
            chunk = f.read(tail_bytes)
        return chunk.decode("utf-8", errors="ignore")
    except OSError as e:
        log.warning("DAILY RADAR: could not read desktop dump %s: %s", dump_path, e)
        return ""


# ---------------------------------------------------------------------------
# Gmail (ideas #3 + #4) — recent emails in the analysis window
# ---------------------------------------------------------------------------

def collect_recent_emails(cfg_id: str,
                          hours: int = ANALYSIS_WINDOW_HOURS,
                          max_results: int = 25,
                          **_) -> Dict[str, Any]:
    """Pull emails received in the last `hours` window.

    Returns `{"emails": [...], "error": str|None}`. Each email is the dict
    returned by `ApiServiceGoogleGmail.get_recent_emails`, truncated for
    payload size: body capped at 800 chars, snippet kept as-is.
    """
    try:
        from apps.apps_config import CONFIG_MANAGER
        from apps.google_apps.references.web.api.gmail import ApiServiceGoogleGmail
    except Exception as e:
        return {"emails": [], "error": "import: {0}".format(e)}

    try:
        cfg = CONFIG_MANAGER.get(cfg_id)
        gmail = ApiServiceGoogleGmail(cfg)
        # Gmail search supports "newer_than:" with a day-granularity quirk —
        # convert hours → days, rounding up so an 8-hour window doesn't miss
        # mail received 7h 30m ago.
        days = max(1, (hours + 23) // 24)
        emails = gmail.get_recent_emails(
            max_results=max_results,
            query="newer_than:{0}d".format(days),
            label_ids=["INBOX"],
        )
    except Exception as e:
        log.warning("DAILY RADAR: gmail fetch failed: %s", e)
        return {"emails": [], "error": str(e)}

    # Now post-filter to the actual 8-hour window using the Date header so
    # we don't ship a full day's worth of inbox to Claude.
    cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)
    trimmed: List[Dict[str, Any]] = []
    for em in emails or []:
        date_str = em.get("date", "")
        if _parse_gmail_date(date_str) < cutoff:
            continue
        trimmed.append({
            "from": em.get("from", ""),
            "subject": em.get("subject", ""),
            "date": date_str,
            "snippet": (em.get("snippet") or "")[:240],
            "body": (em.get("body") or "")[:800],
            "labels": em.get("labelIds") or [],
        })

    return {"emails": trimmed, "error": None}


def _parse_gmail_date(date_str: str) -> datetime:
    """Best-effort parse of an RFC-2822 Date header. Returns epoch on failure."""
    if not date_str:
        return datetime.fromtimestamp(0, tz=timezone.utc)
    try:
        from email.utils import parsedate_to_datetime
        dt = parsedate_to_datetime(date_str)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except Exception:
        return datetime.fromtimestamp(0, tz=timezone.utc)


# ---------------------------------------------------------------------------
# Calendar (idea #17) — today's events, all-day + scheduled
# ---------------------------------------------------------------------------

def collect_calendar_today(cfg_id: str, **_) -> Dict[str, Any]:
    """Return `{"events": [...], "error": str|None}` for today's events."""
    try:
        from apps.apps_config import CONFIG_MANAGER
        from apps.google_apps.references.web.api.calendar import (
            ApiServiceGoogleCalendarEvents,
            EventType,
        )
    except Exception as e:
        return {"events": [], "error": "import: {0}".format(e)}

    try:
        cfg = CONFIG_MANAGER.get(cfg_id)
        cal = ApiServiceGoogleCalendarEvents(cfg)
        events = cal.get_all_events_today(EventType.ALL)
    except Exception as e:
        log.warning("DAILY RADAR: calendar fetch failed: %s", e)
        return {"events": [], "error": str(e)}

    out: List[Dict[str, Any]] = []
    for e in events or []:
        start = (e.get("start") or {})
        end = (e.get("end") or {})
        out.append({
            "summary": e.get("summary", ""),
            "calendar": e.get("calendarSummary", ""),
            "start": start.get("dateTime") or start.get("date") or "",
            "end": end.get("dateTime") or end.get("date") or "",
            "location": e.get("location", ""),
        })
    return {"events": out, "error": None}


# ---------------------------------------------------------------------------
# Google Tasks (idea #17) — open todos across all task lists
# ---------------------------------------------------------------------------

def collect_open_google_tasks(cfg_id: str,
                              max_per_list: int = 25,
                              **_) -> Dict[str, Any]:
    """Return `{"tasks": [...], "error": str|None}` for open Google Tasks."""
    try:
        from apps.apps_config import CONFIG_MANAGER
        from apps.google_apps.references.web.api.tasks import ApiServiceGoogleTasks
    except Exception as e:
        return {"tasks": [], "error": "import: {0}".format(e)}

    try:
        cfg = CONFIG_MANAGER.get(cfg_id)
        svc = ApiServiceGoogleTasks(cfg)
        lists = svc.list_task_lists(max_results=100) or []
    except Exception as e:
        log.warning("DAILY RADAR: tasks list fetch failed: %s", e)
        return {"tasks": [], "error": str(e)}

    out: List[Dict[str, Any]] = []
    for tl in lists:
        tl_id = tl.get("id")
        tl_title = tl.get("title", "")
        if not tl_id:
            continue
        try:
            items = svc.list_tasks(
                tasklist_id=tl_id,
                max_results=max_per_list,
                show_completed=False,
            ) or []
        except Exception as e:
            log.warning("DAILY RADAR: tasks for %s failed: %s", tl_title, e)
            continue
        for t in items:
            out.append({
                "list": tl_title,
                "title": t.get("title", ""),
                "due": t.get("due", ""),
                "notes": (t.get("notes") or "")[:300],
            })
    return {"tasks": out, "error": None}


# ---------------------------------------------------------------------------
# Jira (idea #17 / work context) — recently-updated tickets in window
# ---------------------------------------------------------------------------

def collect_jira_recent_updates(cfg_id: str,
                                hours: int = ANALYSIS_WINDOW_HOURS,
                                max_results: int = 25,
                                **_) -> Dict[str, Any]:
    """Return `{"issues": [...], "error": str|None}` for tickets updated in
    the analysis window.

    Matches the kind of work-context surfacing the JIRA BOARD widget does,
    but scoped to "what moved recently" rather than "what's in my columns".
    JQL: `updated >= -<hours>h ORDER BY updated DESC`, restricted to issues
    that involve the current user (assignee / reporter / commenter) so the
    radar doesn't spam the prompt with the entire org's activity.
    """
    try:
        from apps.apps_config import CONFIG_MANAGER
        from apps.jira.references.web.api.issues import ApiServiceJiraIssues
    except Exception as e:
        return {"issues": [], "error": "import: {0}".format(e)}

    try:
        cfg = CONFIG_MANAGER.get(cfg_id)
        svc = ApiServiceJiraIssues(cfg)
        jql = (
            "(assignee = currentUser() OR reporter = currentUser() "
            "OR watcher = currentUser()) AND updated >= -{0}h "
            "ORDER BY updated DESC"
        ).format(int(hours))
        resp = svc.search_issues(
            jql=jql,
            max_results=max_results,
            fields=["summary", "status", "assignee", "priority", "updated"],
        )
    except Exception as e:
        log.warning("DAILY RADAR: jira fetch failed: %s", e)
        return {"issues": [], "error": str(e)}

    if not isinstance(resp, dict):
        return {"issues": [], "error": "jira: malformed response"}

    out: List[Dict[str, Any]] = []
    for issue in (resp.get("issues") or []):
        fields = issue.get("fields") or {}
        assignee = (fields.get("assignee") or {}).get("displayName", "")
        out.append({
            "key": issue.get("key", ""),
            "summary": (fields.get("summary") or "")[:160],
            "status": (fields.get("status") or {}).get("name", ""),
            "assignee": assignee,
            "priority": (fields.get("priority") or {}).get("name", ""),
            "updated": fields.get("updated", ""),
        })
    return {"issues": out, "error": None}


# ---------------------------------------------------------------------------
# GitHub (idea #4 / work context) — PRs involving me, updated in window
# ---------------------------------------------------------------------------

def collect_github_prs_involving_me(cfg_id: str,
                                    hours: int = ANALYSIS_WINDOW_HOURS,
                                    max_results: int = 25,
                                    **_) -> Dict[str, Any]:
    """Return `{"prs": [...], "error": str|None}` for open PRs involving the
    authenticated user that have moved in the analysis window.

    Uses GitHub's search API with `is:pr is:open involves:@me updated:>...`
    — `involves:@me` covers author, assignee, mentioned, and review-requested,
    which is the right "what should I look at" filter for a daily radar.
    """
    try:
        from apps.apps_config import CONFIG_MANAGER
        from apps.github.references.web.api.repos import ApiServiceGitHubRepos
    except Exception as e:
        return {"prs": [], "error": "import: {0}".format(e)}

    try:
        cfg = CONFIG_MANAGER.get(cfg_id)
        gh = ApiServiceGitHubRepos(cfg)
        cutoff = (datetime.now(timezone.utc) - timedelta(hours=hours)).strftime("%Y-%m-%dT%H:%M:%SZ")
        query = "is:pr is:open involves:@me updated:>{0}".format(cutoff)
        issues = gh.search_issues(query=query, per_page=max_results) or []
    except Exception as e:
        log.warning("DAILY RADAR: github fetch failed: %s", e)
        return {"prs": [], "error": str(e)}

    out: List[Dict[str, Any]] = []
    for it in issues:
        # `search_issues` returns DtoGitHubIssue (search returns PRs as issues).
        # The DTO carries the html_url with `/pull/<n>` so we can tell them
        # apart, plus title / state / labels / assignees / updated_at.
        out.append({
            "title": getattr(it, "title", "") or "",
            "state": getattr(it, "state", "") or "",
            "url": getattr(it, "html_url", "") or "",
            "number": getattr(it, "number", None),
            "author": getattr(it, "user_login", "") or "",
            "labels": getattr(it, "labels", None) or [],
            "assignees": getattr(it, "assignees", None) or [],
            "updated": getattr(it, "updated_at", "") or "",
        })
    return {"prs": out, "error": None}


# ---------------------------------------------------------------------------
# OwnTracks (situational context) — last known location
# ---------------------------------------------------------------------------

def collect_last_location(cfg_id: str,
                          user: Optional[str] = None,
                          device: Optional[str] = None,
                          **_) -> Dict[str, Any]:
    """Return `{"location": dict|None, "error": str|None}` with the most
    recent OwnTracks fix.

    Pure context — the prompt uses it to tailor suggestions ("you're at
    home — pick something light" / "you're at the office — focus on the
    work block"). When `user` / `device` are omitted, the Recorder returns
    the most-recent device across the account.
    """
    try:
        from apps.apps_config import CONFIG_MANAGER
        from apps.own_tracks.references.web.api.locations import (
            ApiServiceOwnTracksLocations,
        )
    except Exception as e:
        return {"location": None, "error": "import: {0}".format(e)}

    try:
        cfg = CONFIG_MANAGER.get(cfg_id)
        svc = ApiServiceOwnTracksLocations(cfg)
        locations = svc.get_last(user=user, device=device) or []
    except Exception as e:
        log.warning("DAILY RADAR: owntracks fetch failed: %s", e)
        return {"location": None, "error": str(e)}

    if not locations:
        return {"location": None, "error": None}

    # Pick the newest fix by `tst` (epoch seconds).
    def _tst(loc: Dict[str, Any]) -> int:
        try:
            return int(loc.get("tst") or 0)
        except Exception:
            return 0

    best = sorted(locations, key=_tst, reverse=True)[0]
    return {
        "location": {
            "user": best.get("username") or best.get("user") or "",
            "device": best.get("device") or best.get("tid") or "",
            "lat": best.get("lat"),
            "lon": best.get("lon"),
            "tst": best.get("tst"),
            "topic": best.get("topic") or "",
        },
        "error": None,
    }


# ---------------------------------------------------------------------------
# ES failed jobs (idea #12) — Celery / workflow failures in window
# ---------------------------------------------------------------------------

def collect_failed_jobs(cfg_id: Optional[str] = None,
                        hours: int = ANALYSIS_WINDOW_HOURS,
                        **_) -> Dict[str, Any]:
    # cfg_id accepted for registry-uniform signature; ES library reads
    # its own env. Pass None or any string — both ignored.
    """Return `{"jobs": [...], "error": str|None}` for failed tasks in window."""
    try:
        from core.apps.es_logging.app.elasticsearch import get_index_data, LOGGING_INDEX
    except Exception as e:
        return {"jobs": [], "error": "import: {0}".format(e)}

    now = datetime.now()
    gte = (now - timedelta(hours=hours)).strftime("%Y-%m-%dT%H:%M")
    lte = now.strftime("%Y-%m-%dT%H:%M")
    query = {
        "bool": {
            "must": [
                {"range": {"last_failed": {"gte": gte, "lte": lte}}}
            ]
        }
    }
    try:
        results = get_index_data(index_name=LOGGING_INDEX, query=query) or []
    except Exception as e:
        log.warning("DAILY RADAR: ES failed-jobs fetch failed: %s", e)
        return {"jobs": [], "error": str(e)}

    out: List[Dict[str, Any]] = []
    for hit in results:
        src = hit.get("_source", {}) or {}
        name_parts = str(src.get("name", "")).split(".")[-2:]
        out.append({
            "task": ".".join(name_parts),
            "error": str(src.get("exception_message", "")).strip()[:200],
            "last_failed": src.get("last_failed", ""),
            "machine": src.get("machine") or "NA",
        })
    return {"jobs": out, "error": None}


# ---------------------------------------------------------------------------
# Trello (idea #12 / agent kanban) — open cards on configured boards
# ---------------------------------------------------------------------------

def collect_trello_cards(cfg_id: str = "TRELLO",
                         max_cards_per_board: int = 30,
                         **_) -> Dict[str, Any]:
    """Return `{"cards": [...], "error": str|None}` for open Trello cards.

    Resolves which board(s) to inspect by walking, in order:
      1. KANBAN_BOARD_ID            (single legacy id)
      2. TRELLO_BOARD_IDS           (comma-separated)
      3. TRELLO_WORKSPACE_ID + name filter
      4. Empty → return `error="no board configured"` so the prompt can
         render "(no Trello board configured)" without breaking.
    """
    try:
        from apps.apps_config import CONFIG_MANAGER
        from apps.trello.references.web.api.boards import ApiServiceTrelloBoards
        from apps.trello.references.web.api.members import ApiServiceTrelloMembers
    except Exception as e:
        return {"cards": [], "error": "import: {0}".format(e)}

    board_ids = _resolve_trello_board_ids()
    if not board_ids:
        try:
            cfg = CONFIG_MANAGER.get(cfg_id)
            members = ApiServiceTrelloMembers(cfg)
            mine = _ensure_list_of_dicts(
                members.get_member_boards("me", filter="open")
            )
        except Exception as e:
            return {"cards": [], "error": "no board configured: {0}".format(e)}
        # Optional name filter (substring, case-insensitive).
        name_filter = (os.environ.get("TRELLO_BOARD_NAME_FILTER") or "").lower().strip()
        exclude = [
            n.strip().lower()
            for n in (os.environ.get("TRELLO_BOARD_NAME_EXCLUDE") or "").split(",")
            if n.strip()
        ]
        for b in mine:
            name = (b.get("name") or "").lower()
            if name_filter and name_filter not in name:
                continue
            if any(x in name for x in exclude):
                continue
            board_ids.append(b.get("id"))

    if not board_ids:
        return {"cards": [], "error": "no board configured"}

    try:
        cfg = CONFIG_MANAGER.get(cfg_id)
        boards_svc = ApiServiceTrelloBoards(cfg)
    except Exception as e:
        return {"cards": [], "error": str(e)}

    out: List[Dict[str, Any]] = []
    for board_id in board_ids[:5]:  # cap at 5 boards to bound payload
        if not board_id:
            continue
        try:
            # `@deserialized(List[dict])` returns the raw `Response` object
            # (not subscriptable, not iterable as expected) when the JSON body
            # fails to parse — e.g. an HTML auth-error page from Trello.
            # `_ensure_list_of_dicts` coerces non-list responses to `[]` so the
            # per-board iteration below never blows up on a malformed reply.
            lists = _ensure_list_of_dicts(
                boards_svc.get_board_lists(board_id, filter="open")
            )
            list_name_by_id = {ls.get("id"): ls.get("name", "") for ls in lists}
            cards = _ensure_list_of_dicts(
                boards_svc.get_board_cards(board_id, filter="open")
            )
            for c in cards[:max_cards_per_board]:
                out.append({
                    "board_id": board_id,
                    "list": list_name_by_id.get(c.get("idList"), ""),
                    "name": c.get("name", ""),
                    "due": c.get("due", ""),
                    "url": c.get("shortUrl", ""),
                })
        except Exception as e:
            log.warning("DAILY RADAR: trello board %s failed: %s", board_id, e)
            continue
    return {"cards": out, "error": None}


def _ensure_list_of_dicts(value: Any) -> List[Dict[str, Any]]:
    """Coerce a possibly-broken API response to a list of dicts.

    `@deserialized(List[dict])` on the Trello services returns the raw
    `Response` object (not a list) when the JSON body fails to parse — see
    `core.web.services.core.decorators.deserializer`. Anything that's not
    a plain list of dicts is dropped to `[]` so the caller's iteration is
    always safe.
    """
    if isinstance(value, list):
        return [v for v in value if isinstance(v, dict)]
    return []


def _resolve_trello_board_ids() -> List[str]:
    """Read board ids from env vars; returns [] when nothing is configured."""
    single = (os.environ.get("KANBAN_BOARD_ID") or "").strip()
    if single:
        return [single]
    multi = (os.environ.get("TRELLO_BOARD_IDS") or "").strip()
    if multi:
        return [b.strip() for b in multi.split(",") if b.strip()]
    return []


# ---------------------------------------------------------------------------
# Aggregator — produces the dict passed to the LLM prompt
# ---------------------------------------------------------------------------

def collect_inputs(sources: List[str],
                   desktop_dump_path: str,
                   hours: int = ANALYSIS_WINDOW_HOURS,
                   source_overrides: Optional[Dict[str, str]] = None,
                   source_params: Optional[Dict[str, Dict[str, Any]]] = None,
                   ) -> Dict[str, Any]:
    """Walk the priority list in `sources`, dispatch each to its collector,
    and return the bundled payload ready for the prompt + summary.

    `sources` is the **priority list** — each name is looked up in
    `SOURCE_REGISTRY`, the collector is called with the default cfg id
    (overridable via `source_overrides`) and default params (overridable
    via `source_params`). Unknown source names are logged and skipped so
    a typo in the beat schedule degrades gracefully.

    Args:
      sources:           ordered list of source names to pull from. The
                         order doubles as the prompt-input ordering —
                         the first entry's section comes first in the
                         LLM input. See `DEFAULT_SOURCES`.
      desktop_dump_path: path to DESKTOP LOGS dump.txt. Always read,
                         independent of `sources` (the desktop log is
                         intrinsic to the radar, not a configurable source).
      hours:             analysis window in hours (passed to every
                         collector that accepts it).
      source_overrides:  per-source cfg id overrides, e.g.
                         ``{"gmail": "GOOGLE_GMAIL_WORK"}``. Defaults to {}.
      source_params:     per-source param overrides, e.g.
                         ``{"owntracks": {"user": "brian"}}``. Each dict
                         is merged on top of the collector's
                         ``default_params``. Defaults to {}.

    Each Google product needs its OWN scoped OAuth token —
    ``GOOGLE_APPS`` (calendar.readonly) is NOT interchangeable with
    ``GOOGLE_GMAIL`` (gmail.readonly) or ``GOOGLE_TASKS`` (tasks). The
    registry pins each source to its correctly-scoped cfg by default.

    A failing collector NEVER raises — it surfaces an ``error`` field on
    its own subsection so the prompt can render ``"<source>
    unavailable"`` cleanly without breaking the rest of the briefing.
    """
    overrides = source_overrides or {}
    params_map = source_params or {}

    payload: Dict[str, Any] = {
        "window_hours": hours,
        "desktop_activity_log": read_desktop_dump_tail(desktop_dump_path),
        # Preserved so format_inputs_as_prompt_text and summarise_inputs
        # can replay the same order without re-deriving it from the keys.
        "_sources": list(sources),
    }

    for name in sources:
        spec = SOURCE_REGISTRY.get(name)
        if spec is None:
            log.warning(
                "DAILY RADAR: unknown source '%s' — not in SOURCE_REGISTRY; skipped",
                name,
            )
            continue
        cfg_id = overrides.get(name, spec.default_cfg)
        params = {**spec.default_params, **params_map.get(name, {})}
        payload[spec.payload_key] = spec.collector(cfg_id, hours=hours, **params)

    return payload


# ---------------------------------------------------------------------------
# Prompt content composer — flattens the aggregator output into a single
# delimited text block for the Claude user turn.
# ---------------------------------------------------------------------------

_SECTION_RULE = "-" * 64


def format_inputs_as_prompt_text(payload: Dict[str, Any]) -> str:
    """Flatten the aggregator payload into a single delimited text block.

    Walks `payload["_sources"]` in order, looking each name up in
    `SOURCE_REGISTRY` to find its `prompt_marker` (the UPPERCASE header
    the LLM expects) and `formatter` (turns the section dict into text).
    Sources whose payload key isn't present are skipped silently —
    happens when a name in the priority list isn't registered.

    The DESKTOP_ACTIVITY_LOG header sits at the top before any registered
    source because the desktop log is intrinsic (always present, never
    configurable).
    """
    parts: List[str] = []
    parts.append("ANALYSIS WINDOW: last {0} hours".format(payload.get("window_hours", 8)))
    parts.append("LOCAL TIME: {0}".format(datetime.now().strftime("%Y-%m-%d %H:%M")))

    parts.append("\n" + _SECTION_RULE)
    parts.append("DESKTOP_ACTIVITY_LOG")
    parts.append(_SECTION_RULE)
    parts.append(payload.get("desktop_activity_log") or "(empty)")

    for name in payload.get("_sources") or []:
        spec = SOURCE_REGISTRY.get(name)
        if spec is None:
            continue
        section = payload.get(spec.payload_key) or {}
        parts.append("\n" + _SECTION_RULE)
        parts.append(spec.prompt_marker)
        parts.append(_SECTION_RULE)
        parts.append(spec.formatter(section))

    return "\n".join(parts)


def _format_emails(section: Dict[str, Any]) -> str:
    if section.get("error"):
        return "(gmail unavailable: {0})".format(section["error"])
    emails = section.get("emails") or []
    if not emails:
        return "(no email)"
    rows = []
    for em in emails:
        rows.append("- FROM: {0}".format(em.get("from", "")))
        rows.append("  SUBJ: {0}".format(em.get("subject", "")))
        rows.append("  DATE: {0}".format(em.get("date", "")))
        snippet = em.get("snippet") or em.get("body") or ""
        if snippet:
            rows.append("  SNIPPET: {0}".format(snippet))
        labels = em.get("labels") or []
        if labels:
            rows.append("  LABELS: {0}".format(",".join(labels)))
        rows.append("")
    return "\n".join(rows).rstrip()


def _format_calendar(section: Dict[str, Any]) -> str:
    if section.get("error"):
        return "(calendar unavailable: {0})".format(section["error"])
    events = section.get("events") or []
    if not events:
        return "(no events)"
    rows = []
    for ev in events:
        rows.append("- {0} | {1} → {2} | cal={3}{4}".format(
            ev.get("summary", ""),
            ev.get("start", ""),
            ev.get("end", ""),
            ev.get("calendar", ""),
            " @ {0}".format(ev["location"]) if ev.get("location") else "",
        ))
    return "\n".join(rows)


def _format_tasks(section: Dict[str, Any]) -> str:
    if section.get("error"):
        return "(google tasks unavailable: {0})".format(section["error"])
    tasks = section.get("tasks") or []
    if not tasks:
        return "(no open tasks)"
    rows = []
    for t in tasks:
        rows.append("- [{0}] {1}{2}{3}".format(
            t.get("list", ""),
            t.get("title", ""),
            " (due: {0})".format(t["due"]) if t.get("due") else "",
            " — {0}".format(t["notes"]) if t.get("notes") else "",
        ))
    return "\n".join(rows)


def _format_trello(section: Dict[str, Any]) -> str:
    if section.get("error"):
        return "(trello unavailable: {0})".format(section["error"])
    cards = section.get("cards") or []
    if not cards:
        return "(no open cards)"
    rows = []
    for c in cards:
        rows.append("- [{0}] {1}{2}".format(
            c.get("list", ""),
            c.get("name", ""),
            " (due: {0})".format(c["due"]) if c.get("due") else "",
        ))
    return "\n".join(rows)


def _format_jira(section: Dict[str, Any]) -> str:
    if section.get("error"):
        return "(jira unavailable: {0})".format(section["error"])
    issues = section.get("issues") or []
    if not issues:
        return "(no recent jira updates)"
    rows = []
    for it in issues:
        rows.append("- {0} [{1}] {2} (assignee={3}, prio={4}) @ {5}".format(
            it.get("key", ""),
            it.get("status", ""),
            it.get("summary", ""),
            it.get("assignee", "") or "-",
            it.get("priority", "") or "-",
            it.get("updated", ""),
        ))
    return "\n".join(rows)


def _format_github_prs(section: Dict[str, Any]) -> str:
    if section.get("error"):
        return "(github unavailable: {0})".format(section["error"])
    prs = section.get("prs") or []
    if not prs:
        return "(no PRs involving me updated in window)"
    rows = []
    for pr in prs:
        labels = ",".join(pr.get("labels") or [])
        rows.append("- #{0} [{1}] {2} (author={3}{4}) @ {5}".format(
            pr.get("number", "?"),
            pr.get("state", "") or "open",
            pr.get("title", ""),
            pr.get("author", "") or "-",
            ", labels=" + labels if labels else "",
            pr.get("updated", ""),
        ))
    return "\n".join(rows)


def _format_last_location(section: Dict[str, Any]) -> str:
    if section.get("error"):
        return "(owntracks unavailable: {0})".format(section["error"])
    loc = section.get("location")
    if not loc:
        return "(no recent location fix)"
    parts = [
        "user={0}".format(loc.get("user") or "-"),
        "device={0}".format(loc.get("device") or "-"),
    ]
    lat = loc.get("lat")
    lon = loc.get("lon")
    if lat is not None and lon is not None:
        parts.append("lat={0}".format(lat))
        parts.append("lon={0}".format(lon))
    tst = loc.get("tst")
    if tst:
        try:
            ts = datetime.fromtimestamp(int(tst))
            parts.append("at={0}".format(ts.strftime("%Y-%m-%d %H:%M")))
        except Exception:
            parts.append("tst={0}".format(tst))
    return "- " + " | ".join(parts)


def _format_failed_jobs(section: Dict[str, Any]) -> str:
    if section.get("error"):
        return "(es failed-jobs unavailable: {0})".format(section["error"])
    jobs = section.get("jobs") or []
    if not jobs:
        return "(no failed jobs)"
    rows = []
    for j in jobs:
        rows.append("- {0} @ {1} on {2} — {3}".format(
            j.get("task", ""),
            j.get("last_failed", ""),
            j.get("machine", ""),
            j.get("error", ""),
        ))
    return "\n".join(rows)


# ---------------------------------------------------------------------------
# Lightweight summary metrics for ES log_result (no LLM call)
# ---------------------------------------------------------------------------

def summarise_inputs(payload: Dict[str, Any]) -> Dict[str, Any]:
    """Return a count-only metrics dict suitable for log_result().

    Counts are emitted as `{source_name}_count` for every registered
    source that has a `count_field` set (e.g. "gmail" → `gmail_count`).
    `sources_errored` lists source names (not payload keys) whose
    collector returned a non-empty `error`. `has_location` is True when
    the owntracks source is active and produced a fix.
    """
    desktop_len = len(payload.get("desktop_activity_log") or "")
    sources = payload.get("_sources") or []

    counts: Dict[str, int] = {}
    errored: List[str] = []
    has_location = False

    for name in sources:
        spec = SOURCE_REGISTRY.get(name)
        if spec is None:
            continue
        section = payload.get(spec.payload_key) or {}
        if section.get("error"):
            errored.append(name)
        if spec.count_field:
            counts["{0}_count".format(name)] = len(
                section.get(spec.count_field) or []
            )
        # OwnTracks is the only source that surfaces a singular dict
        # rather than a list — track it explicitly so callers can branch
        # on "is location available" without inspecting the payload.
        if name == "owntracks":
            has_location = bool(section.get("location"))

    return {
        "window_hours": payload.get("window_hours"),
        "desktop_log_chars": desktop_len,
        "has_location": has_location,
        "sources_active": list(sources),
        "sources_errored": errored,
        **counts,
    }


# ---------------------------------------------------------------------------
# Output formatting — wrap to HUD column width while preserving structure
# ---------------------------------------------------------------------------


def wrap_preserving_breaks(text: str, width: int = 65) -> str:
    """Wrap each non-blank line to `width` while keeping blank lines intact.

    `core.utilities.data.strings.wrap_text` joins everything with spaces
    before re-wrapping, which destroys the daily-radar prompt's section
    structure (headers, bullets, the `====` rules all collapse into a
    single paragraph). This helper wraps each line independently and
    passes blank lines through unchanged so the HUD dump renders as the
    prompt intended.

    Notes:
      - Long unbreakable tokens (URLs, long IDs) are not broken — better
        to overflow the visual column slightly than to split an identifier.
      - Hyphens are not used as break points, so "feat/config-env-injection"
        stays on one line if it fits.
    """
    if not text:
        return ""
    out_lines: List[str] = []
    for line in text.splitlines():
        stripped = line.rstrip()
        if not stripped:
            out_lines.append("")
            continue
        # Preserve any leading indentation on the line.
        indent = line[: len(line) - len(line.lstrip())]
        wrapped = textwrap.fill(
            stripped,
            width=width,
            initial_indent=indent,
            subsequent_indent=indent,
            break_long_words=False,
            break_on_hyphens=False,
            replace_whitespace=False,
        )
        out_lines.append(wrapped)
    return "\n".join(out_lines)


# Re-export the regex helper used by the unit tests to spot-check commitment
# extraction logic. (The actual commitment extraction lives in the LLM prompt;
# this regex is only here so callers can pre-flag obvious phrases for tests.)
_COMMITMENT_RE = re.compile(
    r"\b(i('?ll| will)|let me|we need to|i'?ll follow up|i'?ll get back|"
    r"i'?ll confirm|i'?ll check|i'?ll send|i'?ll raise)\b",
    re.IGNORECASE,
)


def looks_like_commitment(text: str) -> bool:
    """Return True if `text` contains a first-person commitment phrase."""
    if not text:
        return False
    return bool(_COMMITMENT_RE.search(text))


# ---------------------------------------------------------------------------
# Populate SOURCE_REGISTRY — runs at module import time, after every
# collector + formatter above is defined. To plug in a new source, append
# one SourceSpec here (and write the matching collector + formatter
# functions above). The radar's beat schedule then enables it by adding
# the `name` to its `sources=[...]` list. See workflows/hud/README.md.
# ---------------------------------------------------------------------------


def _register_default_sources() -> None:
    SOURCE_REGISTRY.update({
        "gmail": SourceSpec(
            name="gmail",
            default_cfg="GOOGLE_GMAIL",
            collector=collect_recent_emails,
            formatter=_format_emails,
            payload_key="gmail_recent",
            prompt_marker="GMAIL_RECENT",
            count_field="emails",
        ),
        "calendar": SourceSpec(
            name="calendar",
            default_cfg="GOOGLE_APPS",
            collector=collect_calendar_today,
            formatter=_format_calendar,
            payload_key="calendar_today",
            prompt_marker="CALENDAR_TODAY",
            count_field="events",
        ),
        "gtasks": SourceSpec(
            name="gtasks",
            default_cfg="GOOGLE_TASKS",
            collector=collect_open_google_tasks,
            formatter=_format_tasks,
            payload_key="google_tasks_open",
            prompt_marker="GOOGLE_TASKS_OPEN",
            count_field="tasks",
        ),
        "trello": SourceSpec(
            name="trello",
            default_cfg="TRELLO",
            collector=collect_trello_cards,
            formatter=_format_trello,
            payload_key="trello_open_cards",
            prompt_marker="TRELLO_OPEN_CARDS",
            count_field="cards",
        ),
        "jira": SourceSpec(
            name="jira",
            default_cfg="JIRA",
            collector=collect_jira_recent_updates,
            formatter=_format_jira,
            payload_key="jira_recent_updates",
            prompt_marker="JIRA_RECENT_UPDATES",
            count_field="issues",
        ),
        "github": SourceSpec(
            name="github",
            default_cfg="GITHUB",
            collector=collect_github_prs_involving_me,
            formatter=_format_github_prs,
            payload_key="github_prs_involving_me",
            prompt_marker="GITHUB_PRS_INVOLVING_ME",
            count_field="prs",
        ),
        "owntracks": SourceSpec(
            name="owntracks",
            default_cfg="OWN_TRACKS",
            collector=collect_last_location,
            formatter=_format_last_location,
            payload_key="last_location",
            prompt_marker="LAST_LOCATION",
            # `last_location` carries a singular dict, not a list — no
            # count_field; summarise_inputs has a special-case for owntracks
            # that emits `has_location` (bool) instead.
        ),
        "es_failed_jobs": SourceSpec(
            name="es_failed_jobs",
            default_cfg=None,  # ES library reads its own env
            collector=collect_failed_jobs,
            formatter=_format_failed_jobs,
            payload_key="es_failed_jobs",
            prompt_marker="ES_FAILED_JOBS",
            count_field="jobs",
        ),
    })


_register_default_sources()
