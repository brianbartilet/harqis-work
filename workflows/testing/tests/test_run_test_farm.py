"""
Tests for workflows/testing/tasks/test_farm.py.

The whole `workflows/` tree is excluded from the default pytest run
(`addopts = --ignore=workflows/` in pytest.ini), so these only execute when
targeted explicitly:

    pytest workflows/testing/tests/test_run_test_farm.py -v
"""
import pytest

from workflows.testing.tasks.test_farm import (
    run_test_farm,
    _coerce_text,
    _extract_fields,
    _fingerprint,
    _slug,
    _cell,
    _sort_key,
    _render_md,
    _resolve_claude_bin,
)


# ── Workflow (integration) ────────────────────────────────────────────────────

@pytest.mark.skip(reason="Live: hits Jira + spawns the claude CLI per changed "
                         "ticket (consumes Max-subscription quota) and rewrites "
                         "logs/BDD-TEST-FARM.md. Run manually with a real board_id.")
def test__run_test_farm():
    # Reuse the same rapidView id as run-job--show_jira_board.
    run_test_farm(board_id=1790, cfg_id__jira="JIRA")


@pytest.mark.skip(reason="Live: forces regeneration of every detected ticket.")
def test__run_test_farm_force():
    run_test_farm(board_id=1790, cfg_id__jira="JIRA", force=True)


# ── Unit / function ───────────────────────────────────────────────────────────

def _fake_issue(**over):
    fields = {
        "summary": "Reject Campaigns Asia via direct API",
        "assignee": {"displayName": "Brian Bartilet"},
        "priority": {"name": "High"},
        "issuetype": {"name": "Bug"},
        "status": {"name": "In Review"},
        "fixVersions": [{"name": "R26.05"}, {"name": "R26.06"}],
        "description": "AC1: The user cannot create Campaigns Asia.",
        "updated": "2026-05-22T09:00:00.000+0000",
    }
    fields.update(over.pop("fields", {}))
    issue = {"key": "ICON-42", "fields": fields}
    issue.update(over)
    return issue


def test__extract_fields_structure():
    f = _extract_fields(_fake_issue())
    assert f["key"] == "ICON-42"
    assert f["assignee"] == "Brian Bartilet"
    assert f["priority"] == "High"
    assert f["issuetype"] == "Bug"
    assert f["status"] == "In Review"
    assert f["fix_versions"] == ["R26.05", "R26.06"]
    assert "Campaigns Asia" in f["description"]


def test__extract_fields_handles_missing():
    f = _extract_fields({"key": "ICON-1", "fields": {}})
    assert f["assignee"] == "Unassigned"
    assert f["priority"] == "-"
    assert f["fix_versions"] == []
    assert f["description"] == ""


def test__coerce_text_plain_string():
    assert _coerce_text("hello") == "hello"
    assert _coerce_text(None) == ""


def test__coerce_text_adf_dict():
    adf = {
        "type": "doc",
        "content": [
            {"type": "paragraph", "content": [
                {"type": "text", "text": "AC1: foo"},
                {"type": "text", "text": "AC2: bar"},
            ]},
        ],
    }
    out = _coerce_text(adf)
    assert "AC1: foo" in out and "AC2: bar" in out


def test__fingerprint_stable_and_sensitive():
    a = _extract_fields(_fake_issue())
    b = _extract_fields(_fake_issue())
    assert _fingerprint(a) == _fingerprint(b)  # same inputs → same hash

    changed = _extract_fields(_fake_issue(fields={"status": {"name": "Ready"}}))
    assert _fingerprint(a) != _fingerprint(changed)  # status change → new hash


def test__slug():
    assert _slug("ICON-42") == "icon-42"
    assert _slug("HARQIS_7!!") == "harqis-7"


def test__cell_escapes_pipes_and_newlines():
    assert _cell("a | b\nc") == "a \\| b c"


def test__render_md_contains_summary_table_and_sections():
    entries = [{
        **_extract_fields(_fake_issue()),
        "gherkin": "```gherkin\nFeature: X\n```",
        "generated_at": "2026-05-22 09:00",
    }]
    md = _render_md(entries, [], board_id=1790, statuses=["In Review"],
                    generated_at="2026-05-22 09:00")
    assert "# BDD Test Case Farm" in md
    assert "## Summary" in md
    assert "[ICON-42](#icon-42)" in md          # nav link
    assert '<a id="icon-42"></a>' in md          # section anchor
    assert "| Ticket Id | ICON-42 |" in md
    assert "| Last generated | 2026-05-22 09:00 |" in md
    assert "Feature: X" in md                    # embedded gherkin


def test__sort_key_orders_by_type_then_status():
    rows = [
        {"issuetype": "Bug", "status": "New", "key": "B-NEW"},
        {"issuetype": "Story", "status": "In Progress", "key": "S-INP"},
        {"issuetype": "Bug", "status": "Quality Review", "key": "B-QR"},
        {"issuetype": "Story", "status": "Open", "key": "S-OPEN"},   # unknown status → last
        {"issuetype": "Story", "status": "Quality Review", "key": "S-QR"},
    ]
    ordered = [r["key"] for r in sorted(rows, key=_sort_key)]
    # Stories before Bugs; within type: Quality Review, In Progress, New, then other.
    assert ordered == ["S-QR", "S-INP", "S-OPEN", "B-QR", "B-NEW"]


def test__render_md_retained_excluded_from_summary_but_kept_as_section():
    active = [{**_extract_fields(_fake_issue()),
               "gherkin": "```gherkin\nFeature: Active\n```", "generated_at": "2026-05-22 09:00"}]
    retained = [{"key": "ICON-9", "summary": "Old closed thing", "assignee": "X",
                 "priority": "Low", "issuetype": "Bug", "status": "Closed",
                 "fix_versions": [], "gherkin": "```gherkin\nFeature: Old\n```",
                 "generated_at": "2026-05-01 09:00"}]
    md = _render_md(active, retained, board_id=1790, statuses=["In Review"],
                    generated_at="2026-05-22 09:00")
    # Active ticket is in the summary; retained one is not.
    assert "[ICON-42](#icon-42)" in md
    assert "[ICON-9](#icon-9)" not in md
    # Retained section is still present, under the Retained heading, marked.
    assert "Retained — no longer in the active focus columns" in md
    assert '<a id="icon-9"></a>' in md
    assert "Feature: Old" in md
    assert "_(retained)_" in md


def test__resolve_claude_bin_with_override():
    assert _resolve_claude_bin("C:/custom/claude.exe") == "C:/custom/claude.exe"
