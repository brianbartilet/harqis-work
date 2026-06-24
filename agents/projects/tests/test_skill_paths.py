"""Regression tests for project skill path conventions."""

from __future__ import annotations

from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[3]
_TEST_GLOBS = ("test_*.py", "unit_tests_*.py")
_IGNORED_PARTS = {".git", ".venv", "venv", "__pycache__"}


def _test_files() -> list[Path]:
    files: list[Path] = []
    for pattern in _TEST_GLOBS:
        files.extend(REPO_ROOT.rglob(pattern))
    return sorted(
        path for path in files
        if not (_IGNORED_PARTS & set(path.relative_to(REPO_ROOT).parts))
    )


def test_python_tests_reference_canonical_agent_skills():
    stale_refs: list[str] = []
    for path in _test_files():
        text = path.read_text(encoding="utf-8")
        stale_posix = ".claude" + "/skills"
        stale_windows = ".claude" + "\\skills"
        if stale_posix in text or stale_windows in text:
            stale_refs.append(path.relative_to(REPO_ROOT).as_posix())

    assert stale_refs == []
