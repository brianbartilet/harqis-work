#!/usr/bin/env python3
"""Parse pytest smoke-test counts without depending on terminal formatting quirks."""

from __future__ import annotations

import argparse
import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path

_SUMMARY_COUNT = re.compile(r"(?P<count>\d+)\s+(?P<label>passed|failed|skipped|errors?)\b")


@dataclass(frozen=True)
class SmokeCounts:
    passed: int = 0
    failed: int = 0
    skipped: int = 0
    errors: int = 0
    total: int = 0

    def as_tsv(self) -> str:
        return f"{self.passed}\t{self.failed}\t{self.skipped}\t{self.errors}\t{self.total}"


def _integer(element: ET.Element, attribute: str) -> int:
    try:
        return int(element.attrib.get(attribute, "0"))
    except ValueError:
        return 0


def parse_junit(path: Path) -> SmokeCounts:
    """Read counts from pytest's JUnit XML report."""
    root = ET.parse(path).getroot()
    suites = [root] if root.tag == "testsuite" else list(root.findall("./testsuite"))
    tests = sum(_integer(suite, "tests") for suite in suites)
    failed = sum(_integer(suite, "failures") for suite in suites)
    skipped = sum(_integer(suite, "skipped") for suite in suites)
    errors = sum(_integer(suite, "errors") for suite in suites)
    passed = max(tests - failed - skipped - errors, 0)
    return SmokeCounts(passed, failed, skipped, errors, tests)


def parse_pytest_output(output: str) -> SmokeCounts:
    """Fallback parser for runs that exit before producing JUnit XML."""
    summary = ""
    for line in reversed(output.splitlines()):
        if _SUMMARY_COUNT.search(line) or "no tests ran" in line:
            summary = line
            break

    values = {"passed": 0, "failed": 0, "skipped": 0, "errors": 0}
    for match in _SUMMARY_COUNT.finditer(summary):
        label = match.group("label")
        key = "errors" if label.startswith("error") else label
        values[key] = int(match.group("count"))
    total = sum(values.values())
    return SmokeCounts(total=total, **values)


def load_counts(junit_path: Path, output_path: Path) -> SmokeCounts:
    if junit_path.is_file():
        try:
            return parse_junit(junit_path)
        except (ET.ParseError, OSError):
            pass
    output = output_path.read_text(encoding="utf-8", errors="replace") if output_path.is_file() else ""
    return parse_pytest_output(output)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--junit", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    print(load_counts(args.junit, args.output).as_tsv())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
