"""
Tests for `workflows/hud/tasks/hud_jira.show_jira_board`.

Layout:
  1. Workflow (integration) tests first — call the real task with the live
     `JIRA` config. These hit the Jira agile API and require valid creds in
     `.env/apps.env` (`JIRA_DOMAIN`, `JIRA_API_TOKEN`).
  2. Unit / function tests for the pure render helpers — fully offline,
     using fixture issue dicts that mirror the real Jira agile-API response.
"""

import pytest

from unittest.mock import MagicMock

from workflows.hud.tasks.hud_jira import (
    _filter_and_sort_issues,
    _filter_issues_by_assignee,
    _fix_version_sort_key,
    _group_issues_by_status,
    _render_issue_row,
    _render_section,
    _resolve_column_status_ids,
    show_jira_board,
)

# `truncate` and `compute_max_hud_lines` were extracted to
# `workflows.hud.helpers.text` and `.sizing`. Their tests live in
# `test_helpers_text.py` and `test_helpers_sizing.py`.


# ── Workflow (integration) ────────────────────────────────────────────────────

_BOARD_ID = 1790
_DASHBOARD_ID = 24135
_REPOSITORY_ID = 24135
_STRUCTURE_ID = 616


def test__show_jira_board():
    """Live call against the configured Jira board."""
    show_jira_board(
        cfg_id__jira="JIRA",
        board_id=_BOARD_ID,
        dashboard_id=_DASHBOARD_ID,
        repository_id=_REPOSITORY_ID,
        structure_id=_STRUCTURE_ID,
    )


def test__show_jira_board_custom_statuses():
    """Override the default status list — useful for narrowing the focus view."""
    show_jira_board(
        cfg_id__jira="JIRA",
        board_id=_BOARD_ID,
        dashboard_id=_DASHBOARD_ID,
        repository_id=_REPOSITORY_ID,
        structure_id=_STRUCTURE_ID,
        statuses=["In Progress"],
        max_results_per_status=5,
    )


# ── Unit / function — _render_issue_row ───────────────────────────────────────

_SAMPLE_ISSUE = {
    "key": "SEHLAT-42",
    "fields": {
        "summary": "NextJS: Too big cache or memory leak when serving static assets",
        "assignee": {"displayName": "Bartilet, Dick Brian"},
        "priority": {"name": "Blocker"},
        "fixVersions": [{"name": "R26.05"}],
        "issuetype": {"name": "Bug"},
    },
}


def test__render_issue_row_full_data():
    row = _render_issue_row(_SAMPLE_ISSUE)
    assert row.endswith("\n")
    # 88-char layout: " T(6) Summary(40) Assignee(22) FixV(6) Ticket(9)" = 88 chars + \n
    assert len(row.rstrip("\n")) == 88
    assert "Bug" in row
    assert "NextJS" in row
    assert "Bartilet, Dick Brian" in row
    assert "R26.05" in row
    assert "SEHLAT-42" in row                       # ticket key, not priority


def test__render_issue_row_dash_when_no_key():
    """Issue without a `key` field renders '-' in the Ticket column."""
    issue = {
        "fields": {
            "summary": "x", "assignee": None,
            "fixVersions": [], "issuetype": {"name": "Task"},
        },
    }
    row = _render_issue_row(issue)
    # The 9-char ticket column at the end of an 88-char row.
    # With no key → '-' left-aligned in 9 chars.
    assert "-        \n" in row


def test__render_issue_row_truncates_long_summary():
    long = dict(_SAMPLE_ISSUE)
    long_fields = dict(long["fields"])
    long_fields["summary"] = "x" * 200
    long["fields"] = long_fields
    row = _render_issue_row(long)
    assert "..." in row                            # summary was cut down
    assert len(row.rstrip("\n")) == 88            # row width still respected


def test__render_issue_row_unassigned_default():
    """Missing assignee → 'Unassigned'."""
    issue = {
        "fields": {
            "summary": "Story X",
            "assignee": None,
            "priority": {"name": "Major"},
            "fixVersions": [{"name": "R26.06"}],
            "issuetype": {"name": "Story"},
        },
    }
    row = _render_issue_row(issue)
    assert "Unassigned" in row


def test__render_issue_row_no_fix_version_renders_dash():
    issue = {
        "fields": {
            "summary": "Task",
            "assignee": {"displayName": "Anyone"},
            "priority": {"name": "Minor"},
            "fixVersions": [],                       # explicit empty
            "issuetype": {"name": "Task"},
        },
    }
    row = _render_issue_row(issue)
    # Dash placeholder for missing fixVersion (truncated to width=6 just yields "-")
    assert " - " in row or row.endswith("- Minor   \n") or "-     " in row


def test__render_issue_row_handles_missing_fields_gracefully():
    """Sparse Jira response shouldn't crash the renderer."""
    issue = {"fields": {}}
    row = _render_issue_row(issue)
    assert len(row.rstrip("\n")) == 88
    # Defaults: T='?', Summary='', Assignee='Unassigned', FixV='-', Ticket='-'
    assert "?" in row
    assert "Unassigned" in row


# ── Unit / function — _render_section ─────────────────────────────────────────

def test__render_section_header_is_88_wide():
    section = {"status": "In Progress", "issues": []}
    out = _render_section(section)
    lines = out.splitlines()
    # First and third lines are === separators; second line is the title.
    assert lines[0] == "=" * 88
    assert lines[1] == "IN PROGRESS"
    assert lines[2] == "=" * 88


def test__render_section_includes_table_header():
    section = {"status": "Ready", "issues": []}
    out = _render_section(section)
    assert " T      Summary" in out                       # 6-wide T column
    assert "Assignee" in out
    assert "FixV" in out
    assert "Ticket" in out                                  # renamed from Priority
    # Table-header divider is 88 dashes.
    assert "-" * 88 in out


def test__render_section_no_issues_message():
    section = {"status": "In Analysis", "issues": []}
    out = _render_section(section)
    assert "(no issues)" in out


def test__render_section_renders_issues_in_order():
    section = {
        "status": "In Review",
        "issues": [
            {"fields": {
                "summary": "First issue",
                "assignee": {"displayName": "A"},
                "priority": {"name": "Major"},
                "fixVersions": [{"name": "R1"}],
                "issuetype": {"name": "Bug"},
            }},
            {"fields": {
                "summary": "Second issue",
                "assignee": {"displayName": "B"},
                "priority": {"name": "Minor"},
                "fixVersions": [{"name": "R2"}],
                "issuetype": {"name": "Task"},
            }},
        ],
    }
    out = _render_section(section)
    first = out.find("First issue")
    second = out.find("Second issue")
    assert 0 < first < second                              # both rendered, in order


def test__render_section_surfaces_fetch_error():
    section = {"status": "In Progress", "issues": [], "error": "401 Unauthorized"}
    out = _render_section(section)
    assert "401 Unauthorized" in out
    assert "(no issues)" not in out                        # error path skips empty marker


# ── Unit / function — _filter_and_sort_issues ─────────────────────────────────

def _issue(name: str, type_name: str, fix_version: str = "R1") -> dict:
    fix_versions = [{"name": fix_version}] if fix_version else []
    return {
        "fields": {
            "summary": name,
            "assignee": {"displayName": "anyone"},
            "priority": {"name": "Major"},
            "fixVersions": fix_versions,
            "issuetype": {"name": type_name},
        },
    }


def test__filter_and_sort_issues__drops_unwanted_types():
    """Sub-tasks, Epics and other niche types are filtered out."""
    issues = [
        _issue("sub", "Sub-task"),
        _issue("story-1", "Story"),
        _issue("epic", "Epic"),
        _issue("bug-1", "Bug"),
        _issue("spike", "Spike"),
        _issue("task-1", "Task"),
    ]
    out = _filter_and_sort_issues(issues)
    kept_types = [i["fields"]["issuetype"]["name"] for i in out]
    assert kept_types == ["Story", "Bug", "Task"]


def test__filter_and_sort_issues__sort_order_story_bug_task():
    """Even when input is in reverse rank order, output is Story → Bug → Task."""
    issues = [
        _issue("task-1", "Task"),
        _issue("bug-1", "Bug"),
        _issue("story-1", "Story"),
    ]
    out = _filter_and_sort_issues(issues)
    summaries = [i["fields"]["summary"] for i in out]
    assert summaries == ["story-1", "bug-1", "task-1"]


def test__filter_and_sort_issues__preserves_intra_type_order():
    """Two stories keep their input order; sort is stable on the type rank."""
    issues = [
        _issue("story-A", "Story"),
        _issue("story-B", "Story"),
        _issue("bug-1", "Bug"),
        _issue("story-C", "Story"),
    ]
    out = _filter_and_sort_issues(issues)
    summaries = [i["fields"]["summary"] for i in out]
    assert summaries == ["story-A", "story-B", "story-C", "bug-1"]


def test__filter_and_sort_issues__handles_missing_issuetype_field():
    """A sparse upstream payload with no issuetype is dropped, not crashed."""
    issues = [
        _issue("story-1", "Story"),
        {"fields": {}},                     # no issuetype at all
        {},                                  # no fields key
        _issue("bug-1", "Bug"),
    ]
    out = _filter_and_sort_issues(issues)
    summaries = [i["fields"]["summary"] for i in out]
    assert summaries == ["story-1", "bug-1"]


def test__filter_and_sort_issues__empty_input_returns_empty():
    assert _filter_and_sort_issues([]) == []


# ── Unit / function — _fix_version_sort_key (secondary sort) ──────────────────

@pytest.mark.parametrize("name,bucket", [
    ("R26.05",                0),    # dated release
    ("R26.06",                0),
    ("R25.12",                0),
    ("v1.0",                  0),    # any non-empty, non-RI string is bucket 0
    ("",                      1),    # empty
    ("-",                     1),    # explicit dash
    (None,                    1),    # missing
    ("Release Independent",   2),
    ("release independent",   2),    # case-insensitive
    ("RELEASE INDEPENDENT",   2),
])
def test__fix_version_sort_key__bucket(name, bucket):
    """First tuple element identifies the bucket."""
    assert _fix_version_sort_key(name)[0] == bucket


def test__fix_version_sort_key__within_bucket_alphabetical():
    """R26.05 sorts before R26.06 alphabetically (also chronologically)."""
    assert _fix_version_sort_key("R26.05") < _fix_version_sort_key("R26.06")
    assert _fix_version_sort_key("R25.12") < _fix_version_sort_key("R26.01")


def test__fix_version_sort_key__bucket_order():
    """Dated < empty < Release Independent."""
    assert _fix_version_sort_key("R26.05") < _fix_version_sort_key("-")
    assert _fix_version_sort_key("-") < _fix_version_sort_key("Release Independent")


def test__filter_and_sort_issues__secondary_sort_by_fix_version():
    """Within a single issue type, sort by (R-version → empty → Release Independent)."""
    issues = [
        _issue("story-empty",      "Story", fix_version=""),
        _issue("story-rel-indep",  "Story", fix_version="Release Independent"),
        _issue("story-r2606",      "Story", fix_version="R26.06"),
        _issue("story-r2605",      "Story", fix_version="R26.05"),
    ]
    out = _filter_and_sort_issues(issues)
    summaries = [i["fields"]["summary"] for i in out]
    assert summaries == [
        "story-r2605",
        "story-r2606",
        "story-empty",
        "story-rel-indep",
    ]


def test__filter_and_sort_issues__type_rank_dominates_fix_version():
    """A Story with no FixVersion still ranks before a Bug with R26.05."""
    issues = [
        _issue("bug-r2605",   "Bug",   fix_version="R26.05"),
        _issue("story-empty", "Story", fix_version=""),
    ]
    out = _filter_and_sort_issues(issues)
    summaries = [i["fields"]["summary"] for i in out]
    assert summaries == ["story-empty", "bug-r2605"]


def test__filter_and_sort_issues__combined_full_ranking():
    """Story + Bug + Task with mixed FixVersion across all three buckets."""
    issues = [
        _issue("task-r2605",       "Task",  fix_version="R26.05"),
        _issue("bug-rel-indep",    "Bug",   fix_version="Release Independent"),
        _issue("story-r2606",      "Story", fix_version="R26.06"),
        _issue("bug-empty",        "Bug",   fix_version=""),
        _issue("story-empty",      "Story", fix_version=""),
        _issue("story-r2605",      "Story", fix_version="R26.05"),
        _issue("bug-r2605",        "Bug",   fix_version="R26.05"),
    ]
    out = _filter_and_sort_issues(issues)
    summaries = [i["fields"]["summary"] for i in out]
    assert summaries == [
        # Story bucket
        "story-r2605",
        "story-r2606",
        "story-empty",
        # Bug bucket
        "bug-r2605",
        "bug-empty",
        "bug-rel-indep",
        # Task bucket
        "task-r2605",
    ]


# ── Unit / function — _group_issues_by_status ────────────────────────────────

def _issue_with_status(
    name: str,
    type_name: str,
    status_name: str,
    key: str = "X-1",
    status_id: str = None,
) -> dict:
    return {
        "key": key,
        "fields": {
            "summary": name,
            "assignee": {"displayName": "x"},
            "priority": {"name": "Major"},
            "fixVersions": [{"name": "R1"}],
            "issuetype": {"name": type_name},
            "status": {"name": status_name, "id": status_id},
        },
    }


def test__group_issues_by_status__buckets_by_status_name():
    """Each issue lands in the section matching its `fields.status.name`."""
    issues = [
        _issue_with_status("a", "Story", "In Review", key="A-1"),
        _issue_with_status("b", "Bug",   "In Progress", key="B-1"),
        _issue_with_status("c", "Task",  "In Progress", key="C-1"),
        _issue_with_status("d", "Story", "Ready", key="D-1"),
    ]
    sections = _group_issues_by_status(
        issues, ["In Review", "In Progress", "Ready", "In Analysis"],
    )
    by_name = {s["status"]: s["issues"] for s in sections}
    assert [i["key"] for i in by_name["In Review"]] == ["A-1"]
    # In Progress: Story → Bug → Task sort means C-1 (Task) is last.
    assert [i["key"] for i in by_name["In Progress"]] == ["B-1", "C-1"]
    assert [i["key"] for i in by_name["Ready"]] == ["D-1"]
    assert by_name["In Analysis"] == []


def test__group_issues_by_status__case_insensitive_match():
    """Jira display value 'IN PROGRESS' still buckets into our 'In Progress'."""
    issues = [_issue_with_status("a", "Story", "IN PROGRESS")]
    sections = _group_issues_by_status(issues, ["In Progress"])
    assert len(sections[0]["issues"]) == 1


def test__group_issues_by_status__trims_whitespace():
    """Trailing whitespace on the Jira side doesn't break bucketing."""
    issues = [_issue_with_status("a", "Story", "  In Progress  ")]
    sections = _group_issues_by_status(issues, ["In Progress"])
    assert len(sections[0]["issues"]) == 1


def test__group_issues_by_status__drops_unrequested_statuses():
    """Issues whose status isn't in the requested list are silently dropped."""
    issues = [
        _issue_with_status("a", "Story", "Done"),                 # not requested
        _issue_with_status("b", "Story", "In Progress"),
    ]
    sections = _group_issues_by_status(issues, ["In Progress"])
    assert [i["fields"]["summary"] for i in sections[0]["issues"]] == ["b"]


def test__group_issues_by_status__filters_to_focus_types():
    """Sub-tasks / Epics in the right status are still dropped by the type filter."""
    issues = [
        _issue_with_status("a", "Sub-task", "In Progress"),
        _issue_with_status("b", "Epic",     "In Progress"),
        _issue_with_status("c", "Story",    "In Progress"),
    ]
    sections = _group_issues_by_status(issues, ["In Progress"])
    assert [i["fields"]["summary"] for i in sections[0]["issues"]] == ["c"]


def test__group_issues_by_status__caps_per_section():
    """A section never renders more than `max_per_section` rows."""
    issues = [
        _issue_with_status(f"s{i}", "Story", "In Progress", key=f"S-{i}")
        for i in range(20)
    ]
    sections = _group_issues_by_status(issues, ["In Progress"], max_per_section=5)
    assert len(sections[0]["issues"]) == 5


def test__group_issues_by_status__preserves_section_order():
    """Output sections come back in the order the caller requested."""
    issues = [
        _issue_with_status("a", "Story", "In Progress", key="A-1"),
        _issue_with_status("b", "Story", "Ready", key="B-1"),
    ]
    sections = _group_issues_by_status(issues, ["Ready", "In Progress"])
    assert [s["status"] for s in sections] == ["Ready", "In Progress"]


def test__group_issues_by_status__handles_missing_status_field():
    """Sparse `fields.status` payload doesn't crash — the issue is dropped."""
    issues = [{"fields": {"issuetype": {"name": "Story"}}}]
    sections = _group_issues_by_status(issues, ["In Progress"])
    assert sections[0]["issues"] == []


# ── Column-id based bucketing (the real fix for custom Jira statuses) ─────────

def test__group_issues_by_status__id_match_wins_over_name_when_map_provided():
    """When `column_status_ids[col]` is populated, the issue's `status.id`
    is matched against the set — name doesn't have to match the column."""
    issues = [
        # Status name says "Code Review" — wouldn't match column "In Review"
        # by name. But its id (10001) is on our In Review column.
        _issue_with_status("a", "Story", "Code Review", key="A-1", status_id="10001"),
        _issue_with_status("b", "Story", "QA Review",   key="B-1", status_id="10002"),
        # Different id (10003) — not in any of our requested columns' id sets.
        _issue_with_status("c", "Story", "Done",        key="C-1", status_id="10003"),
    ]
    column_status_ids = {
        "In Review":   {"10001", "10002"},
        "In Progress": {"3"},
    }
    sections = _group_issues_by_status(
        issues, ["In Review", "In Progress"],
        column_status_ids=column_status_ids,
    )
    by_name = {s["status"]: s["issues"] for s in sections}
    assert [i["key"] for i in by_name["In Review"]] == ["A-1", "B-1"]
    assert by_name["In Progress"] == []


def test__group_issues_by_status__falls_back_to_name_when_col_has_no_ids():
    """Empty id-set for a column → fall back to status-name match.

    Useful when the configuration call partially failed or only some
    columns were resolved.
    """
    issues = [_issue_with_status("a", "Story", "In Progress", key="A-1", status_id="3")]
    column_status_ids = {
        "In Review": {"10001"},     # populated → id-only
        "In Progress": set(),        # empty   → name fallback
    }
    sections = _group_issues_by_status(
        issues, ["In Review", "In Progress"],
        column_status_ids=column_status_ids,
    )
    by_name = {s["status"]: s["issues"] for s in sections}
    assert by_name["In Review"] == []
    assert [i["key"] for i in by_name["In Progress"]] == ["A-1"]


def test__group_issues_by_status__id_lookup_drops_id_only_in_other_column():
    """Issues whose id matches a non-requested column are still dropped."""
    issues = [_issue_with_status("a", "Story", "Done", key="A-1", status_id="999")]
    column_status_ids = {"In Progress": {"3"}}
    sections = _group_issues_by_status(
        issues, ["In Progress"], column_status_ids=column_status_ids,
    )
    assert sections[0]["issues"] == []


# ── Unit / function — _resolve_column_status_ids ─────────────────────────────

def test__resolve_column_status_ids__builds_map_from_board_config():
    """The configuration response is walked column-by-column."""
    api = MagicMock()
    api.get_configuration.return_value = {
        "id": 1790,
        "columnConfig": {
            "columns": [
                {"name": "Backlog",     "statuses": [{"id": "1"}]},                     # not requested
                {"name": "In Review",   "statuses": [{"id": "10001"}, {"id": "10002"}]},
                {"name": "In Progress", "statuses": [{"id": "3"}]},
                {"name": "Done",        "statuses": [{"id": "5"}]},                     # not requested
            ],
        },
    }
    out = _resolve_column_status_ids(api, 1790, ["In Review", "In Progress", "Ready"])
    assert out["In Review"] == {"10001", "10002"}
    assert out["In Progress"] == {"3"}
    # Requested but absent from the config → empty set (fallback to name match).
    assert out["Ready"] == set()


def test__resolve_column_status_ids__case_insensitive_column_match():
    """Trailing whitespace / different case on the Jira side still matches."""
    api = MagicMock()
    api.get_configuration.return_value = {
        "columnConfig": {
            "columns": [
                {"name": "  IN PROGRESS ", "statuses": [{"id": "3"}]},
            ],
        },
    }
    out = _resolve_column_status_ids(api, 1790, ["In Progress"])
    assert out["In Progress"] == {"3"}


def test__resolve_column_status_ids__falls_back_to_empty_on_api_failure():
    """If the config call raises, return empty sets — caller falls back to name match."""
    api = MagicMock()
    api.get_configuration.side_effect = RuntimeError("403 forbidden")
    out = _resolve_column_status_ids(api, 1790, ["In Review", "In Progress"])
    assert out == {"In Review": set(), "In Progress": set()}


def test__resolve_column_status_ids__empty_statuses_list():
    """A column with no underlying statuses → empty set, not missing key."""
    api = MagicMock()
    api.get_configuration.return_value = {
        "columnConfig": {
            "columns": [{"name": "In Review", "statuses": []}],
        },
    }
    out = _resolve_column_status_ids(api, 1790, ["In Review"])
    assert out["In Review"] == set()


# ── Unit / function — _filter_issues_by_assignee ─────────────────────────────


def _make_issue(*, summary: str, assignee_display: str | None,
                issue_type: str = "Task", key: str = "X-1") -> dict:
    """Tiny fixture builder for assignee-filter tests."""
    fields = {
        "summary": summary,
        "issuetype": {"name": issue_type},
        "fixVersions": [],
    }
    if assignee_display is not None:
        fields["assignee"] = {"displayName": assignee_display}
    return {"key": key, "fields": fields}


def test__filter_issues_by_assignee__exact_match():
    """displayName matches case-insensitively."""
    issues = [
        _make_issue(summary="A", assignee_display="Bartilet, Dick Brian Reario", key="X-1"),
        _make_issue(summary="B", assignee_display="Someone Else", key="X-2"),
        _make_issue(summary="C", assignee_display="bartilet, dick brian reario", key="X-3"),
    ]
    out = _filter_issues_by_assignee(issues, "Bartilet, Dick Brian Reario")
    keys = {i["key"] for i in out}
    assert keys == {"X-1", "X-3"}


def test__filter_issues_by_assignee__handles_missing_assignee():
    """Issues with no assignee never match."""
    issues = [
        _make_issue(summary="A", assignee_display=None, key="X-1"),
        _make_issue(summary="B", assignee_display="Me", key="X-2"),
    ]
    out = _filter_issues_by_assignee(issues, "Me")
    assert [i["key"] for i in out] == ["X-2"]


def test__filter_issues_by_assignee__empty_target_returns_empty():
    """An empty / whitespace `assignee_name` returns no matches (safe default)."""
    issues = [
        _make_issue(summary="A", assignee_display="Anyone", key="X-1"),
    ]
    assert _filter_issues_by_assignee(issues, "") == []
    assert _filter_issues_by_assignee(issues, "   ") == []
    assert _filter_issues_by_assignee(issues, None) == []


def test__filter_issues_by_assignee__sorts_like_status_sections():
    """Result is run through `_filter_and_sort_issues` (Story → Bug → Task)."""
    issues = [
        _make_issue(summary="task", assignee_display="Me", issue_type="Task", key="X-3"),
        _make_issue(summary="story", assignee_display="Me", issue_type="Story", key="X-1"),
        _make_issue(summary="bug", assignee_display="Me", issue_type="Bug", key="X-2"),
        _make_issue(summary="epic", assignee_display="Me", issue_type="Epic", key="X-4"),
    ]
    out = _filter_issues_by_assignee(issues, "Me")
    assert [i["key"] for i in out] == ["X-1", "X-2", "X-3"]


# `_compute_max_hud_lines` tests live in `test_helpers_sizing.py` now.
