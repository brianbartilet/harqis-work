#!/usr/bin/env python3
"""Sync canonical repo skills into Claude's compatibility directory.

Usage:
  python scripts/agents/repo-quality/sync_agent_skills.py
  python scripts/agents/repo-quality/sync_agent_skills.py --check

The source of truth is .agents/skills. Claude-compatible copies are generated
under .claude/skills and are intentionally ignored by git.
"""

from __future__ import annotations

import argparse
import filecmp
import shutil
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[3]
SOURCE = REPO_ROOT / ".agents" / "skills"
TARGET = REPO_ROOT / ".claude" / "skills"


def _has_frontmatter(path: Path) -> bool:
    lines = path.read_text(encoding="utf-8").splitlines()
    if len(lines) < 4 or lines[0] != "---":
        return False
    try:
        closing = lines[1:].index("---") + 1
    except ValueError:
        return False
    header = lines[1:closing]
    return any(line.startswith("name: ") for line in header) and any(
        line.startswith("description: ") for line in header
    )


def validate_source() -> list[str]:
    errors: list[str] = []
    if not SOURCE.is_dir():
        return [f"missing source directory: {SOURCE}"]

    skill_files = sorted(SOURCE.glob("*/SKILL.md"))
    if not skill_files:
        errors.append(f"no skills found under {SOURCE}")

    for skill_file in skill_files:
        if not _has_frontmatter(skill_file):
            errors.append(f"invalid frontmatter: {skill_file.relative_to(REPO_ROOT)}")
    return errors


def trees_match() -> bool:
    if not TARGET.exists():
        return False
    comparison = filecmp.dircmp(SOURCE, TARGET)
    return _dircmp_clean(comparison)


def _dircmp_clean(comparison: filecmp.dircmp[str]) -> bool:
    if comparison.left_only or comparison.right_only or comparison.diff_files or comparison.funny_files:
        return False
    return all(_dircmp_clean(child) for child in comparison.subdirs.values())


def sync() -> None:
    errors = validate_source()
    if errors:
        for error in errors:
            print(error, file=sys.stderr)
        raise SystemExit(1)

    TARGET.parent.mkdir(parents=True, exist_ok=True)
    if TARGET.exists():
        shutil.rmtree(TARGET)
    shutil.copytree(SOURCE, TARGET)
    print(f"synced {SOURCE.relative_to(REPO_ROOT)} -> {TARGET.relative_to(REPO_ROOT)}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--check",
        action="store_true",
        help="validate frontmatter and verify .claude/skills already matches .agents/skills",
    )
    args = parser.parse_args()

    errors = validate_source()
    if errors:
        for error in errors:
            print(error, file=sys.stderr)
        return 1

    if args.check:
        if trees_match():
            print(".claude/skills is in sync with .agents/skills")
            return 0
        print(".claude/skills is not in sync with .agents/skills", file=sys.stderr)
        return 1

    sync()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
