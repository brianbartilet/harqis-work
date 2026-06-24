#!/usr/bin/env python3
"""
Bi-monthly HARQIS migrate-to-core runner.

Runs Claude Code locally against the canonical .agents skill so Hermes cron can
schedule the work with no Hermes agent/API reasoning loop. The script is quiet on
off-cycle Saturdays so no_agent cron delivery stays silent.
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
CORE_DEFAULT = Path.home() / "GIT" / "harqis-core"
SKILL_PATH = REPO_ROOT / ".agents" / "skills" / "migrate-to-core" / "SKILL.md"
SCAN_SCRIPT = REPO_ROOT / "scripts" / "agents" / "repo-quality" / "migrate_to_core_scan.py"
DATA_DIR = Path("/Volumes/harqis-data/migrate-to-core")
CLAUDE_BIN = Path.home() / ".local" / "bin" / "claude"


def is_first_or_third_saturday(now: datetime) -> bool:
    # Python Monday=0, Saturday=5. First Saturday is day 1-7, third is 15-21.
    return now.weekday() == 5 and (1 <= now.day <= 7 or 15 <= now.day <= 21)


def run(cmd: list[str], cwd: Path = REPO_ROOT, timeout: int = 60) -> subprocess.CompletedProcess[str]:
    return subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, timeout=timeout)


def check_preconditions(core_path: Path) -> list[str]:
    failures: list[str] = []

    if not CLAUDE_BIN.exists():
        failures.append(f"Claude Code binary missing: {CLAUDE_BIN}")
    else:
        auth = run([str(CLAUDE_BIN), "auth", "status", "--text"], timeout=45)
        auth_text = (auth.stdout + auth.stderr).strip()
        if auth.returncode != 0 or "not logged in" in auth_text.lower():
            failures.append("Claude Code is not logged in to the Max/OAuth subscription (`claude auth login`).")

    if shutil.which("gh") is None:
        failures.append("GitHub CLI `gh` is not installed or not on PATH; the skill creates PRs with gh.")
    else:
        gh = run(["gh", "auth", "status"], timeout=45)
        if gh.returncode != 0:
            failures.append("GitHub CLI `gh` is not authenticated.")

    if not core_path.exists():
        failures.append(f"harqis-core checkout missing: {core_path}")
    elif not (core_path / ".git").exists():
        failures.append(f"harqis-core path is not a git checkout: {core_path}")

    for required in (SKILL_PATH, SCAN_SCRIPT):
        if not required.exists():
            failures.append(f"Required file missing: {required}")

    return failures


def build_prompt(core_path: Path, max_pairs: int) -> str:
    skill_markdown = SKILL_PATH.read_text(encoding="utf-8")
    timestamp = datetime.now().isoformat()
    return f"""/migrate-to-core --max {max_pairs} --core-path {core_path}

You are Claude Code running under Brian's local Claude Max subscription. Execute the HARQIS-work `/migrate-to-core` skill headlessly, using the full canonical skill markdown included below as the source of truth.

Operating constraints:
- Repo: {REPO_ROOT}
- Core repo: {core_path}
- Timestamp: {timestamp}
- Use the repo venv Python for Python commands when available: `.venv/bin/python` on macOS/Linux or `.venv/Scripts/python.exe` on Windows.
- Run the deterministic scan first: `scripts/agents/repo-quality/migrate_to_core_scan.py`.
- Ingest harqis-core before proposing anything: README.md, core/docs/FEATURES.md, and the relevant core subpackages.
- Open at most {max_pairs} candidate PR pairs.
- Never auto-merge anything.
- Respect the exclusions: workflows, AI/Claude scaffold, HFL, Kanban, MCP, manifesto-specific code.
- If preconditions fail or no candidates survive judgment/idempotency checks, write a concise report and stop cleanly.
- Save a run report under {DATA_DIR}/migrate_to_core_{datetime.now().strftime('%Y-%m-%d')}.md and print the same summary to stdout.

Full canonical skill markdown:

```markdown
{skill_markdown}
```
"""


def main() -> int:
    parser = argparse.ArgumentParser(description="Run /migrate-to-core via local Claude Code on first/third Saturdays.")
    parser.add_argument("--force", action="store_true", help="Run even when today is not the first or third Saturday.")
    parser.add_argument("--check-only", action="store_true", help="Check preconditions without invoking Claude Code.")
    parser.add_argument("--max", type=int, default=3, help="Maximum candidate PR pairs for the skill run.")
    parser.add_argument("--core-path", default=os.environ.get("HARQIS_CORE_PATH", str(CORE_DEFAULT)))
    args = parser.parse_args()

    now = datetime.now()
    if not args.force and not is_first_or_third_saturday(now):
        return 0  # quiet off-cycle; no_agent cron sends nothing on empty stdout

    core_path = Path(args.core_path).expanduser().resolve()
    DATA_DIR.mkdir(parents=True, exist_ok=True)

    print("[migrate-to-core-agent] Starting HARQIS /migrate-to-core Claude Code run")
    print(f"[migrate-to-core-agent] Repo: {REPO_ROOT}")
    print(f"[migrate-to-core-agent] Core: {core_path}")
    print(f"[migrate-to-core-agent] Skill: {SKILL_PATH}")

    failures = check_preconditions(core_path)
    if failures:
        print("[migrate-to-core-agent] Preconditions failed:")
        for failure in failures:
            print(f"- {failure}")
        return 1

    if args.check_only:
        print("[migrate-to-core-agent] Preconditions OK; check-only mode, not invoking Claude Code.")
        return 0

    prompt = build_prompt(core_path=core_path, max_pairs=args.max)
    cmd = [
        str(CLAUDE_BIN),
        "-p",
        prompt,
        "--model",
        "sonnet",
        "--effort",
        "high",
        "--max-turns",
        "25",
        "--allowedTools",
        "Read,Write,Edit,Bash,Glob,Grep",
    ]

    result = subprocess.run(cmd, cwd=REPO_ROOT, capture_output=True, text=True, timeout=3600)
    if result.stdout:
        print(result.stdout)
    if result.stderr:
        print(result.stderr, file=sys.stderr)
    return result.returncode


if __name__ == "__main__":
    raise SystemExit(main())
