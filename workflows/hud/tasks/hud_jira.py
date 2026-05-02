"""
JIRA BOARD HUD widget.

Pulls issues from a single Jira Software board (the same `rapidView` id that
appears in the board URL) for each focus status — "In Review", "In Progress",
"Ready", "In Analysis" — and renders them as one section per status on the
desktop HUD. The header carries a JIRA_BOARD link that opens the source
RapidBoard in the user's default browser.

References:
- `workflows/hud/tasks/hud_tcg.show_tcg_orders` — layout / dimension reference.
- `apps/jira/references/web/api/boards.ApiServiceJiraBoards` — agile API.
"""

import os
from typing import List, Optional

from core.apps.sprout.app.celery import SPROUT
from core.apps.es_logging.app.elasticsearch import log_result
from core.utilities.logging.custom_logger import logger as log
from core.utilities.data.strings import make_separator
from core.utilities.resources.decorators import get_decorator_attrs

from apps.rainmeter.references.helpers.config_builder import ConfigHelperRainmeter, init_meter
from apps.desktop.helpers.feed import feed

from apps.jira.references.web.api.boards import ApiServiceJiraBoards
from apps.google_apps.references.constants import ScheduleCategory

from apps.rainmeter.config import CONFIG as RAINMETER_CONFIG
from apps.jira.config import APP_NAME as APP_NAME_JIRA
from apps.apps_config import CONFIG_MANAGER

from workflows.hud.helpers.layout import compute_horizontal_link_layout
from workflows.hud.helpers.sizing import (
    DEFAULT_MAX_HUD_LINES,
    compute_max_hud_lines,
)
from workflows.hud.helpers.text import truncate
from workflows.hud.tasks.sections import sections__jira_board


# Statuses pulled per run, in display order. Tweak by passing
# `statuses=[...]` to the task call.
DEFAULT_STATUSES: List[str] = [
    "In Review",
    "In Progress",
    "Ready",
    "In Analysis",
]

# Issue fields requested from Jira. Smaller payload + faster response.
# `status` is needed for client-side grouping into sections; `priority` is no
# longer rendered (the rightmost column shows `issue.key` now), but kept here
# as a low-cost field in case the renderer evolves.
_JIRA_FIELDS: List[str] = [
    "summary",
    "assignee",
    "priority",
    "fixVersions",
    "issuetype",
    "status",
]

# JQL filter applied to every board fetch. `sprint in openSprints()` keeps
# the focus view scoped to the active sprint(s) and excludes backlog tickets.
# When between sprints the query returns zero issues — every section shows
# "(no issues)".
_SPRINT_FILTER_JQL: str = "sprint in openSprints()"

# Cap on how many issues to pull from the board per run. A single sprint
# rarely exceeds this; if it does, the overflow rows simply don't render
# (better than slow-rendering the whole backlog).
_MAX_BOARD_ISSUES: int = 200

# Only these issue types are surfaced in the HUD. Sub-tasks, Epics, Spikes,
# etc. are noise for the focus view. Order matters — used as the row sort
# rank below (Story → Bug → Task).
_INCLUDED_ISSUE_TYPES: tuple = ("Story", "Bug", "Task")
_TYPE_SORT_RANK: dict = {name: i for i, name in enumerate(_INCLUDED_ISSUE_TYPES)}

# Display name for the synthesised "assigned to me" section that prepends
# the status columns. Picked up by the renderer as the section title and by
# the metrics payload as the key in `by_section`.
_ASSIGNED_TO_ME_LABEL: str = "ASSIGNED TO ME"


@SPROUT.task()
@log_result()
@init_meter(RAINMETER_CONFIG, hud_item_name='JIRA BOARD',
            new_sections_dict=sections__jira_board,
            play_sound=False,
            schedule_categories=[ScheduleCategory.WORK, ])
@feed()
def show_jira_board(board_id: int,
                    dashboard_id: int,
                    repository_id: int,
                    structure_id: int,
                    ini=ConfigHelperRainmeter(),
                    statuses: Optional[List[str]] = None,
                    max_results_per_status: int = 20,
                    max_hud_lines: int = DEFAULT_MAX_HUD_LINES,
                    **kwargs):
    """Render the JIRA BOARD HUD widget.

    URLs for the four header links are built from the Jira domain
    (`apps_config.yaml::JIRA.app_data.domain`, populated from `JIRA_DOMAIN`)
    plus the IDs passed as kwargs. This keeps the schedule entry tidy:
    `"board_id": 1790` instead of pasting the full RapidBoard URL.

    Args:
        board_id:               `rapidView=<id>` — opens the agile board.
        dashboard_id:           `selectPageId=<id>` — opens a Jira dashboard.
        repository_id:          `selectPageId=<id>` — opens a Jira dashboard
                                (typically a different page than `dashboard_id`).
        structure_id:           `s=<id>` — opens a Structure plugin board.
        statuses:               Status names to render, in display order.
                                Default: ["In Review", "In Progress",
                                "Ready", "In Analysis"].
        max_results_per_status: Cap per status section. Default 20.
        max_hud_lines:          Visible HUD height in lines. The widget
                                auto-shrinks to actual content below this cap;
                                content beyond it scrolls via mouse-wheel.
                                Default `DEFAULT_MAX_HUD_LINES` (14).
        ini:                    ini config
    Kwargs
        cfg_id__jira:           Config key for Jira (default 'JIRA').

    Returns:
        Multi-section text dump piped to the Rainmeter HUD via @feed.
    """
    log.info("show_jira_board kwargs: %s", list(kwargs.keys()))

    # region Fetch
    cfg_id__jira = kwargs.get('cfg_id__jira', APP_NAME_JIRA)
    cfg__jira = CONFIG_MANAGER.get(cfg_id__jira)

    # Build all header URLs from the configured Jira domain so the schedule
    # entry can pass clean numeric IDs instead of pasting full URLs.
    domain = cfg__jira.app_data['domain']
    board_url      = f"https://{domain}/secure/RapidBoard.jspa?rapidView={board_id}"
    dashboard_url  = f"https://{domain}/secure/Dashboard.jspa?selectPageId={dashboard_id}"
    repository_url = f"https://{domain}/secure/Dashboard.jspa?selectPageId={repository_id}"
    structure_url  = f"https://{domain}/secure/StructureBoard.jspa?s={structure_id}#"

    api_boards = ApiServiceJiraBoards(cfg__jira)

    statuses = statuses or DEFAULT_STATUSES

    # Pull the board's column → status-id map. The board's column "In Review"
    # can map to underlying statuses with different names ("Code Review",
    # "QA Review", etc.), so direct status-name matching misses them. With
    # the map we bucket by *column membership* using status IDs.
    # Falls back silently to status-name matching if the config call fails.
    column_status_ids = _resolve_column_status_ids(api_boards, board_id, statuses)

    # One sprint-scoped call → group client-side. Replaces the previous
    # per-status JQL loop, which mis-bucketed tickets when a status display
    # name didn't exactly match a board column header.
    try:
        response = api_boards.get_board_issues(
            board_id=board_id,
            jql=_SPRINT_FILTER_JQL,
            fields=_JIRA_FIELDS,
            max_results=_MAX_BOARD_ISSUES,
        )
        issues_all = (response or {}).get("issues", []) or []
    except Exception as e:
        log.warning("show_jira_board: failed to fetch board %s: %s", board_id, e)
        issues_all = []
        fetch_error: Optional[str] = str(e)
        sections: List[dict] = [
            {"status": s, "issues": [], "error": fetch_error} for s in statuses
        ]
    else:
        fetch_error = None
        sections = _group_issues_by_status(
            issues_all, statuses,
            max_per_section=max_results_per_status,
            column_status_ids=column_status_ids,
        )

    # Prepend the "ASSIGNED TO ME" section using the same sprint payload —
    # filter by `fields.assignee.displayName == cfg__jira.app_data.user`
    # case-insensitively. Skipped silently when no `user` is configured so
    # the HUD keeps working for callers that haven't set the field yet.
    current_user = (cfg__jira.app_data or {}).get('user')
    if current_user:
        assigned_issues = _filter_issues_by_assignee(issues_all, current_user)
        sections.insert(0, {
            "status": _ASSIGNED_TO_ME_LABEL,
            "issues": assigned_issues[:max_results_per_status],
            "error": fetch_error,
        })
    # endregion

    # region Build links — header
    # Five clickable header labels, positioned dynamically via the layout
    # helper so adding/renaming a label doesn't require eyeballing X coords.
    # Labels appear left-to-right; second-and-onwards labels get a leading
    # `|` separator in the rendered text (matches show_tcg_orders style:
    # 'JIRA_BOARD|DUMP|DASHBOARD|REPOSITORY|STRUCTURE').
    meta = get_decorator_attrs(show_jira_board, prefix='')
    hud_item = str(meta['_hud_item_name']).replace(" ", "").upper()
    dump_path = os.path.join(
        RAINMETER_CONFIG['write_skin_to_path'],
        RAINMETER_CONFIG['skin_name'],
        hud_item,
        "dump.txt",
    )

    # User-supplied links first; DUMP appended last as a placeholder for
    # quickly viewing the rendered text file (mirrors the convention the
    # /create-new-hud skill scaffolds — see header-links pattern there).
    header_labels = ["BOARD", "DASHBOARD", "REPOSITORY", "STRUCTURE", "DUMP"]
    layout = compute_horizontal_link_layout(header_labels)

    # 0 — BOARD (template default `meterLink` slot, no `|` prefix).
    x0, w0 = layout[0]
    ini['meterLink']['text'] = header_labels[0]
    ini['meterLink']['leftmouseupaction'] = '!Execute ["{0}" 3]'.format(board_url)
    ini['meterLink']['tooltiptext'] = board_url
    ini['meterLink']['X'] = '({0}*#Scale#)'.format(x0)
    ini['meterLink']['W'] = str(w0)

    # 1+ — additional `meterLink_*` slots; each gets a `|<LABEL>` prefix.
    # `exec_arg='3'` opens the URL in the system default browser; the DUMP
    # entry is a local path so it skips the arg.
    extra_links = [
        ("meterLink_dashboard",  header_labels[1], dashboard_url,  "3"),
        ("meterLink_repository", header_labels[2], repository_url, "3"),
        ("meterLink_structure",  header_labels[3], structure_url,  "3"),
        ("meterLink_dump",       header_labels[4], dump_path,      None),
    ]
    for i, (slot, label, target, exec_arg) in enumerate(extra_links, start=1):
        x, w = layout[i]
        ini[slot]['Meter'] = 'String'
        ini[slot]['MeterStyle'] = 'sItemLink'
        ini[slot]['X'] = '({0}*#Scale#)'.format(x)
        ini[slot]['Y'] = '(38*#Scale#)'
        ini[slot]['W'] = str(w)
        ini[slot]['H'] = '55'
        ini[slot]['Text'] = '|{0}'.format(label)
        action = '!Execute ["{0}" {1}]'.format(target, exec_arg) if exec_arg \
            else '!Execute ["{0}"]'.format(target)
        ini[slot]['LeftMouseUpAction'] = action
        ini[slot]['tooltiptext'] = target
    # endregion

    # region Compose dump (sized BEFORE dimension assignment so the HUD can
    # crop to the actual content height — see `helpers/sizing.compute_max_hud_lines`)
    dump = ""
    for section in sections:
        dump += _render_section(section)
        dump += "\n"

    if not any(s.get("issues") for s in sections):
        dump += "\nNo issues on board {0} for the selected statuses.\n\n".format(board_id)

    dump = dump + "\n"
    # endregion

    # region Set dimensions — height auto-cropped to dump line count + buffer
    width_multiplier = 3
    max_hud_lines = compute_max_hud_lines(dump, cap=max_hud_lines)

    ini['meterSeperator']['W'] = '({0}*186*#Scale#)'.format(width_multiplier)
    ini['MeterDisplay']['W'] = '({0}*190*#Scale#)'.format(width_multiplier)
    # SkinHeight must be > Background height by ~6 px so the StrokeWidth=1
    # border has room to render.
    ini['MeterDisplay']['H'] = '((42*#Scale#)+(#ItemLines#*22)*#Scale#)'

    ini['Rainmeter']['SkinWidth'] = '({0}*198*#Scale#)'.format(width_multiplier)
    ini['Rainmeter']['SkinHeight'] = '((42*#Scale#)+(#ItemLines#*22)*#Scale#)'

    ini['MeterBackground']['Shape'] = ('Rectangle 0,0,({0}*190),(36+(#ItemLines#*22)),2 | Fill Color #fillColor# '
                                       '| StrokeWidth (1*#Scale#) | Stroke Color [#darkColor] '
                                       '| Scale #Scale#,#Scale#,0,0').format(width_multiplier)
    ini['MeterBackgroundTop']['Shape'] = ('Rectangle 3,3,({0}*187),25,2 | Fill Color #headerColor# | StrokeWidth 0 '
                                          '| Stroke Color [#darkColor] | Scale #Scale#,#Scale#,0,0').format(width_multiplier)

    ini['meterTitle']['W'] = '({0}*190*#Scale#)'.format(width_multiplier)
    ini['meterTitle']['X'] = '({0}*190*#Scale#)/2'.format(width_multiplier)

    ini['MeterDisplay']['MeasureName'] = 'MeasureScrollableText'
    ini['Variables']['ItemLines'] = '{0}'.format(max_hud_lines)
    # endregion

    # region Build frontend payload
    # Per-section counts let the frontend render a compact summary card
    # (e.g. "BOARD · 12 issues · IN PROGRESS=4, REVIEW=3, READY=5") without
    # having to parse the dump text. Section names are kept in the order
    # the renderer used so the UI ordering matches the HUD ordering.
    by_section = {
        s.get("status"): len(s.get("issues") or [])
        for s in sections
    }
    # `total_issues` counts column rows only — exclude the synthesised
    # "ASSIGNED TO ME" section to avoid double-counting (those issues
    # also appear in their respective status column).
    assigned_count = by_section.get(_ASSIGNED_TO_ME_LABEL, 0)
    total_issues = sum(c for name, c in by_section.items() if name != _ASSIGNED_TO_ME_LABEL)
    errors = [s.get("status") for s in sections if s.get("error")]
    summary_parts = [f"{name.upper()}={count}" for name, count in by_section.items()
                     if name != _ASSIGNED_TO_ME_LABEL]
    base_summary = "{0} issue(s) · {1}".format(total_issues, ", ".join(summary_parts)) \
        if summary_parts else "no issues"
    summary = "MINE={0} · {1}".format(assigned_count, base_summary) \
        if current_user else base_summary
    # endregion

    return {
        "text": dump,
        "summary": summary,
        "metrics": {
            "board_id": board_id,
            "total_issues": total_issues,
            "assigned_to_me": assigned_count,
            "current_user": current_user,
            "by_section": by_section,
            "errors": errors,
        },
        "links": {
            "board": board_url,
            "dashboard": dashboard_url,
            "repository": repository_url,
            "structure": structure_url,
        },
    }


# ── Rendering helpers ─────────────────────────────────────────────────────────

def _render_section(section: dict) -> str:
    """Render one status section: header bar + table header + rows."""
    status = section["status"]
    issues = section.get("issues") or []
    error = section.get("error")

    # Section header (uppercase status between two 88-wide separators).
    out = "{sep}\n{title}\n{sep}\n".format(
        sep=make_separator(88, '='),
        title=status.upper(),
    )

    # Column header — same widths as the data rows.
    # Layout: " T(6) Summary(40) Assignee(22) FixV(6) Ticket(9)" = 88 chars
    out += " {0:<6} {1:<40} {2:<22} {3:<6} {4:<9}\n".format(
        "T", "Summary", "Assignee", "FixV", "Ticket",
    )
    out += make_separator(88, '-') + "\n"

    if error:
        out += " (error fetching issues: {0})\n".format(error)
        return out

    if not issues:
        out += " (no issues)\n"
        return out

    for issue in issues:
        out += _render_issue_row(issue)

    return out


def _render_issue_row(issue: dict) -> str:
    """Render one issue as an 88-char row matching the column header."""
    fields = (issue or {}).get("fields", {}) or {}

    issuetype = (fields.get("issuetype") or {}).get("name") or "?"
    summary = fields.get("summary") or ""
    assignee = (fields.get("assignee") or {}).get("displayName") or "Unassigned"
    ticket = (issue or {}).get("key") or "-"

    # First fixVersion only — the HUD has no room for a list.
    fix_versions = fields.get("fixVersions") or []
    fix_version = fix_versions[0]["name"] if fix_versions else "-"

    return " {0:<6} {1:<40} {2:<22} {3:<6} {4:<9}\n".format(
        truncate(issuetype, 6),
        truncate(summary, 40),
        truncate(assignee, 22),
        truncate(fix_version, 6),
        truncate(ticket, 9),
    )


def _resolve_column_status_ids(api_boards, board_id: int, columns: List[str]) -> dict:
    """Map each requested board column → set of underlying Jira status IDs.

    Calls `/rest/agile/1.0/board/{id}/configuration` and walks the
    `columnConfig.columns[].statuses[].id` tree, keeping only the columns
    the caller asked about. Matching column names is case-insensitive +
    whitespace-trimmed.

    Returns `{column_name: set(status_ids)}`. Empty set for a column means
    "no underlying status — fall back to status-name matching" (which is
    also what happens silently if the config call fails). Always returns a
    dict keyed by every requested column name (with an empty set when
    unmapped) so callers don't need to special-case missing keys.
    """
    requested_lc = {c.strip().lower(): c for c in columns}
    out: dict = {c: set() for c in columns}
    try:
        config = api_boards.get_configuration(board_id) or {}
    except Exception as e:
        log.warning(
            "show_jira_board: board configuration unavailable — "
            "falling back to status-name matching: %s", e,
        )
        return out

    for col in (config.get("columnConfig") or {}).get("columns", []) or []:
        col_name = (col.get("name") or "").strip()
        canonical = requested_lc.get(col_name.lower())
        if canonical is None:
            continue
        ids = {s.get("id") for s in (col.get("statuses") or []) if s.get("id")}
        out[canonical] = {str(i) for i in ids}
    return out


def _group_issues_by_status(
    issues: List[dict],
    statuses: List[str],
    max_per_section: int = 20,
    column_status_ids: Optional[dict] = None,
) -> List[dict]:
    """Bucket a flat issue list into one section per requested status.

    Two matching strategies, applied per requested column:

      1. **By status ID** (when `column_status_ids[col]` is populated) — the
         board's configuration was successfully read and we know exactly
         which underlying statuses live in this column. Use this whenever
         possible: a column named "In Review" may map to statuses named
         "Code Review", "QA Review", etc., that wouldn't match by name.

      2. **By status name** (fallback when the column's id-set is empty) —
         case-insensitive + whitespace-trimmed match against
         `fields.status.name`. Used when the board configuration call
         failed or didn't return a mapping for the column.

    Each section is also passed through `_filter_and_sort_issues`
    (Story → Bug → Task) and capped at `max_per_section` rows.

    Returns a list of `{"status": <display name>, "issues": [...]}` in the
    same order as `statuses`.
    """
    column_status_ids = column_status_ids or {}
    by_col: dict = {s: [] for s in statuses}

    for issue in issues:
        status_field = ((issue or {}).get("fields") or {}).get("status") or {}
        status_id = str(status_field.get("id")) if status_field.get("id") else None
        status_name = (status_field.get("name") or "").strip().lower()

        for col in statuses:
            id_set = column_status_ids.get(col) or set()
            if id_set:
                if status_id and status_id in id_set:
                    by_col[col].append(issue)
                    break
            else:
                # Fallback: name match against the column display name.
                if status_name and status_name == col.strip().lower():
                    by_col[col].append(issue)
                    break

    sections: List[dict] = []
    for status in statuses:
        bucket = _filter_and_sort_issues(by_col[status])
        sections.append({"status": status, "issues": bucket[:max_per_section]})
    return sections


def _fix_version_sort_key(name: str) -> tuple:
    """Return a sort key for a FixVersion name. Lower tuple sorts first.

    Buckets, in display order:
      0. `R<YY>.<MM>` releases (and any other named version) — sorted
         ascending so `R26.05` appears before `R26.06`.
      1. Empty / `-` / missing — appear after dated releases.
      2. `Release Independent` — always last.

    Tuples compare element-by-element, so ("0", "R26.05") < ("0", "R26.06")
    < ("1", "") < ("2", ""). The string suffix is only used to break ties
    *within* bucket 0.
    """
    name = (name or "").strip()
    if not name or name == "-":
        return (1, "")
    if name.lower() == "release independent":
        return (2, "")
    return (0, name)


def _first_fix_version(issue: dict) -> str:
    """Extract the first `fixVersions[].name` for sort + display purposes."""
    fix_versions = ((issue or {}).get("fields") or {}).get("fixVersions") or []
    return fix_versions[0]["name"] if fix_versions else ""


def _filter_issues_by_assignee(issues: List[dict], assignee_name: str) -> List[dict]:
    """Return the subset of `issues` assigned to `assignee_name`, sorted.

    Match is case-insensitive + whitespace-trimmed against
    `fields.assignee.displayName`. Issues with no assignee never match.
    The result is run through `_filter_and_sort_issues` for the same
    Story → Bug → Task → fixVersion ordering used by the status columns,
    so the "ASSIGNED TO ME" section reads consistently with the rest.
    """
    target = (assignee_name or "").strip().lower()
    if not target:
        return []
    matches: List[dict] = []
    for issue in issues:
        assignee = (((issue or {}).get("fields") or {}).get("assignee") or {})
        display = (assignee.get("displayName") or "").strip().lower()
        if display == target:
            matches.append(issue)
    return _filter_and_sort_issues(matches)


def _filter_and_sort_issues(issues: List[dict]) -> List[dict]:
    """Keep only `_INCLUDED_ISSUE_TYPES` and sort by (type, fix_version).

    Sub-tasks, Epics, Spikes, and other niche types are dropped — they're
    noise on the focus HUD. The kept rows are sorted stably by:

      1. Issue type rank — Story → Bug → Task.
      2. FixVersion bucket — `R<YY>.<MM>` releases first (ascending),
         then empty / `-`, then `Release Independent` last.

    Ties on both keys keep their input order (whatever Jira returned).
    """
    filtered = []
    for issue in issues:
        type_name = (((issue or {}).get("fields") or {}).get("issuetype") or {}).get("name")
        if type_name in _INCLUDED_ISSUE_TYPES:
            filtered.append(issue)
    return sorted(
        filtered,
        key=lambda i: (
            _TYPE_SORT_RANK.get(
                (((i or {}).get("fields") or {}).get("issuetype") or {}).get("name") or "",
                len(_TYPE_SORT_RANK),
            ),
            _fix_version_sort_key(_first_fix_version(i)),
        ),
    )


# NOTE: `_truncate` and `_compute_max_hud_lines` were moved to
# `workflows/hud/helpers/text.py` and `workflows/hud/helpers/sizing.py`
# respectively — they're generic enough that any HUD widget can use them.
# Imports at the top of this module pull them in as `truncate` and
# `compute_max_hud_lines`.
