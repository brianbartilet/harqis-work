from datetime import date

from workflows.hfl.mcp import _is_weekly_rollup, _summary_overlaps


def test_weekly_rollup_recognizes_current_and_legacy_names():
    assert _is_weekly_rollup("2026-W30-rollup")
    assert _is_weekly_rollup("_summary-2026-W30")
    assert not _is_weekly_rollup("2026-07-21")


def test_weekly_rollup_iso_week_overlaps_requested_window():
    assert _summary_overlaps(
        "2026-W30-rollup",
        date(2026, 7, 21),
        date(2026, 7, 21),
    )
    assert not _summary_overlaps(
        "2026-W30-rollup",
        date(2026, 8, 1),
        date(2026, 8, 7),
    )
