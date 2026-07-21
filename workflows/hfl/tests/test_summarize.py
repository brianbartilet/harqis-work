from pathlib import Path

from workflows.hfl.tasks.summarize import (
    _render_rollup,
    _rollup_filename,
    _rollup_tags,
)


def _entry(date: str, tags: str) -> dict[str, str]:
    return {
        "date": date,
        "header": f"{date} 09:00",
        "body": (
            "Moment: A useful moment\n"
            "What happened: Something happened\n"
            f"Tags: {tags}\n"
        ),
    }


def test_rollup_tags_include_week_metadata_and_source_entry_tags():
    entries = [
        _entry("2026-07-20", "#jira #testing"),
        _entry("2026-07-21", "#notes #testing"),
    ]

    tags = _rollup_tags(entries, 2026, 30)

    assert tags == (
        "weekly",
        "summary",
        "2026-W30",
        "jira",
        "notes",
        "testing",
    )


def test_rollup_filename_uses_iso_year_and_zero_padded_week():
    assert _rollup_filename(2026, 3) == "2026-W03-rollup.md"


def test_render_rollup_adds_searchable_tags_section():
    entries = [_entry("2026-07-21", "#jira #notes")]

    rendered = _render_rollup(
        "## Themes\n- A recurring theme",
        entries,
        [Path("2026-07-21.md")],
        window_days=7,
        iso_year=2026,
        iso_week=30,
    )

    assert rendered.startswith("# Weekly rollup — 2026-W30\n")
    assert rendered.index("## Themes") < rendered.index("## Tags")
    assert rendered.endswith(
        "## Tags\nTags: #weekly #summary #2026-W30 #jira #notes\n\n"
    )
