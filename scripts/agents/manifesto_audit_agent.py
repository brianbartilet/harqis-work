#!/usr/bin/env python3
"""
Manifesto Audit Agent - Delegated to Claude Code CLI
Runs locally (no API cost). Audits HARQIS-work repo for CODE+PARA compliance,
generates findings, and creates PR branches for significant issues.

Usage:
  python scripts/agents/manifesto_audit_agent.py

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

REPO_ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = Path("/Volumes/harqis-data")
CLAUDE_CODE_BIN = Path.home() / ".local" / "bin" / "claude"


def run_cmd(cmd, cwd=None, capture=True):
    """Run shell command, optionally capturing output."""
    try:
        result = subprocess.run(
            cmd,
            shell=True,
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
    1. Run manifesto_audit.py + improvement_scout.py
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

    # Build Claude Code prompt
    prompt = f"""You are an expert auditor of HARQIS-work, a Python/Celery automation platform.
Your task: Execute a comprehensive manifesto audit and generate improvement PRs.

CONTEXT:
- Repo: {REPO_ROOT}
- Data output: {DATA_DIR}
- Timestamp: {datetime.now().isoformat()}

AUDIT SCOPE (treat manifesto as soft guidance, not hard constraints):
1. Manifesto metadata: code_role, express_target completeness in workflow/app manifesto blocks
2. Capture→Organize→Distill→Express flow tracing (orphaned captures, observable paths)
3. Habit 5: Code reuse, app utilization, pattern drift
4. PAER adoption: Plan-Analyze-Execute-Review loops closed?
5. HFL integration: Signal captured → ingested → distilled → re-expressed?
6. Technical debt: Dead code, underutilized apps, test coverage gaps
7. Documentation alignment: Manifesto blocks, READMEs, onboarding

TASKS:
1. Run: python scripts/manifesto_audit.py → parse output for metadata gaps
2. Run: python scripts/daily_improvement_scout.py → capture quality signals
3. Run: git log --oneline -30 → understand recent 2-3 month changes
4. Structural scan:
   - find workflows -name tasks_config.py → list all beat entries
   - ls -1 apps/ → app inventory
   - grep "from apps\\." workflows/ agents/ --include="*.py" → usage scan
   - find workflows agents -name "test*.py" → test coverage
5. Trace 3-5 workflows end-to-end: Capture → Organize → Distill → Express (are paths observable?)
6. Synthesize findings, rank by severity (CRITICAL → HIGH → MEDIUM) + leverage
7. For each HIGH+ finding with code implications:
   - Create a feature branch: git checkout -b audit/fix-<issue>
   - Make the rewrite (using this tool's code capabilities)
   - Create a PR with description: title, evidence, impact, rationale
   - Push and output PR link
8. Save findings:
   - Markdown narrative: {DATA_DIR}/manifesto_audit_{datetime.now().strftime('%Y-%m-%d')}.md
   - Structured JSON: {DATA_DIR}/manifesto_audit_{datetime.now().strftime('%Y-%m-%d')}.json

FINDING FORMAT (markdown + JSON):
- CRITICAL: Blocks Express paths, breaks CI/CD, framework credibility at risk
- HIGH: Regression risk, onboarding pain, missing infrastructure
- MEDIUM: Technical debt, code cleanup, optional leverage
- Per finding: Signal, Evidence (paths/counts), Impact, Express output, Next actions, Effort (hours)

MANIFEST AUDIT OUTPUT TO STDOUT when done:
=== MANIFESTO AUDIT COMPLETE ===
<summary: X CRITICAL, Y HIGH, Z MEDIUM findings>
<total effort estimate>
<top 3 leverage points>
<PR links>
Files:
- {DATA_DIR}/manifesto_audit_*.md
- {DATA_DIR}/manifesto_audit_*.json
=== END ===

Go."""

    # Call Claude Code with the audit prompt
    cmd = f'{CLAUDE_CODE_BIN} "{prompt}"'
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
        print(f"\n[manifesto-audit-agent] ✓ Audit complete.")
        print(f"[manifesto-audit-agent] Findings: {md_file}")
        print(f"[manifesto-audit-agent] Structured: {json_file}")
    else:
        print(f"\n[manifesto-audit-agent] ✗ Audit failed or incomplete.")
        print(f"[manifesto-audit-agent] Expected: {md_file}, {json_file}")

    sys.exit(exit_status)


if __name__ == "__main__":
    main()
