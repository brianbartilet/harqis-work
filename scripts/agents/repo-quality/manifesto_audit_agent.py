#!/usr/bin/env python3
"""
Manifesto Audit Agent - Delegated to Claude Code CLI
Compatibility launcher for the provider-neutral manifesto-audit skill. Audits CODE+PARA compliance,
generates findings, and creates PR branches for significant issues.

Usage:
  python scripts/agents/repo-quality/manifesto_audit_agent.py

Output:
  - /Volumes/harqis-data/manifesto_audit_<date>.md (narrative findings)
  - /Volumes/harqis-data/manifesto_audit_<date>.json (structured findings)
  - GitHub PR branches + PR descriptions (ready for review)
  - Stdout: summary and PR links
"""

import json
import subprocess
import sys
from datetime import datetime
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
DATA_DIR = Path("/Volumes/harqis-data")
SKILL_PATH = REPO_ROOT / ".agents" / "skills" / "manifesto-audit" / "SKILL.md"
CLAUDE_CODE_BIN = Path.home() / ".local" / "bin" / "claude"


def run_cmd(cmd, cwd=None, capture=True):
    """Run shell command, optionally capturing output."""
    try:
        result = subprocess.run(
            cmd,
            shell=False,
            cwd=cwd or REPO_ROOT,
            capture_output=capture,
            text=True,
            timeout=300,
        )
        return result.stdout + result.stderr, result.returncode
    except subprocess.TimeoutExpired:
        return f"TIMEOUT (>300s): {cmd}", 1
    except Exception as e:
        return f"ERROR: {e}", 1


def main():
    """
    Delegate the entire manifesto audit to Claude Code.
    Claude Code will:
    1. Read the shared manifesto-audit skill and gather evidence
    2. Analyze git history, trace CODE+PARA flows
    3. Generate ranked findings
    4. For HIGH+ findings: create rewrite PRs
    5. Output: markdown narrative + JSON structured findings
    """

    print("[manifesto-audit-agent] Starting manifesto audit via Claude Code...")
    print(f"[manifesto-audit-agent] Repo: {REPO_ROOT}")
    print(f"[manifesto-audit-agent] Claude Code: {CLAUDE_CODE_BIN}")

    # Ensure data dir exists
    DATA_DIR.mkdir(parents=True, exist_ok=True)

    # Keep audit methodology in the shared skill, not in a provider adapter.
    skill = SKILL_PATH.read_text(encoding="utf-8")
    today = datetime.now().strftime("%Y-%m-%d")
    prompt = f"""Execute the manifesto-audit skill below in this checkout: {REPO_ROOT}.
Output directory: {DATA_DIR}
Exact report filenames: manifesto_audit_{today}.md and manifesto_audit_{today}.json.
This scheduled job requests fixes and draft PRs for substantiated HIGH or CRITICAL
findings. Use isolated worktrees; leave the runtime checkout on its original branch.
Do not merge or deploy. Report findings and any successfully created PR links.

{skill}
"""

    # Call Claude Code with the audit prompt
    cmd = [str(CLAUDE_CODE_BIN), "-p", prompt]
    print(f"\n[manifesto-audit-agent] Running Claude Code...")
    output, returncode = run_cmd(cmd)

    # Print output
    print(output)

    # Verify output files exist
    today = datetime.now().strftime("%Y-%m-%d")
    md_file = DATA_DIR / f"manifesto_audit_{today}.md"
    json_file = DATA_DIR / f"manifesto_audit_{today}.json"

    success = md_file.exists() and json_file.exists()
    exit_status = 0 if success and returncode == 0 else 1

    if success:
        print(f"\n[manifesto-audit-agent] Audit complete.")
        print(f"[manifesto-audit-agent] Findings: {md_file}")
        print(f"[manifesto-audit-agent] Structured: {json_file}")
    else:
        print(f"\n[manifesto-audit-agent] Audit failed or incomplete.")
        print(f"[manifesto-audit-agent] Expected: {md_file}, {json_file}")

    sys.exit(exit_status)


if __name__ == "__main__":
    main()
