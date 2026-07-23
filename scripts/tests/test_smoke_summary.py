from __future__ import annotations

from pathlib import Path

from scripts.agents.testing.smoke_summary import SmokeCounts, parse_junit, parse_pytest_output


def test_parse_junit_counts_pytest_testsuite(tmp_path: Path) -> None:
    report = tmp_path / "smoke.xml"
    report.write_text(
        '<?xml version="1.0" encoding="utf-8"?>'
        '<testsuites name="pytest tests">'
        '<testsuite name="pytest" errors="1" failures="2" skipped="3" tests="12" time="1.0" />'
        '</testsuites>',
        encoding="utf-8",
    )

    assert parse_junit(report) == SmokeCounts(
        passed=6,
        failed=2,
        skipped=3,
        errors=1,
        total=12,
    )


def test_parse_pytest_output_uses_final_summary_without_duplicate_zeroes() -> None:
    output = """
ERROR collecting apps/example/tests/test_api.py
================ 1 failed, 177 passed, 33 skipped, 1 error in 212.00s ================
"""

    assert parse_pytest_output(output) == SmokeCounts(
        passed=177,
        failed=1,
        skipped=33,
        errors=1,
        total=212,
    )


def test_parse_pytest_output_before_collection_returns_integer_zeroes() -> None:
    output = """ERROR: usage: pytest [options]\npytest: error: unrecognized arguments: --timeout=30\n"""

    counts = parse_pytest_output(output)

    assert counts == SmokeCounts(passed=0, failed=0, skipped=0, errors=0, total=0)
    assert counts.as_tsv() == "0\t0\t0\t0\t0"
