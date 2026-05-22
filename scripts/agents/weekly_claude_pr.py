#!/usr/bin/env python3
"""
Weekly orchestration: run improvement scout, delegate to local Claude Code, create PR.
- Runs improvement_scout.py for continuous scanning
- Passes findings to local Claude Code for branch creation + PR
- Creates draft PR ready for review
- Targets: /harqis-work/skills and /harqis-work/agents/projects context
"""

import subprocess
import json
import os
import sys
from datetime import datetime
from pathlib import Path

REPO_ROOT = Path(__file__).parents[2]
HARQIS_DATA = REPO_ROOT / ".harqis-data"
CLAUDE_BIN = "/Users/harqis-one/.local/bin/claude"

def run_improvement_scout():
    """Run continuous scanning via daily_improvement_scout.py"""
    print(f"[{datetime.now().isoformat()}] Running improvement scout...")
    result = subprocess.run(
        ["python", "scripts/agents/daily_improvement_scout.py"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        timeout=300,
    )
    
    if result.returncode != 0:
        print(f"Scout failed: {result.stderr}")
        sys.exit(1)
    
    # Load latest findings
    scout_output = HARQIS_DATA / "improvement_scout_latest.json"
    if not scout_output.exists():
        print("No scout output found")
        sys.exit(1)
    
    with open(scout_output) as f:
        findings = json.load(f)
    
    print(f"Scout found {len(findings.get('findings', []))} items")
    return findings

def prepare_claude_task(findings):
    """Format findings for Claude Code"""
    task = f"""
You are orchestrating a weekly improvement PR for HARQIS-work.

## Context
- Repo: /Users/harqis-one/GIT/harqis-work
- Skills context: /harqis-work/skills (load .claude/skills/ to see manifesto-aligned improvements)
- Agents context: /harqis-work/agents/projects (Kanban orchestrator, task agents)

## Task
1. Read the latest findings JSON from .harqis-data/improvement_scout_latest.json
2. Create a feature branch: `feat/weekly-improvements-$(date +%Y%m%d)`
3. For each finding (ranked by severity):
   - Update relevant README.md or code documentation
   - Add a structured summary to .harqis-data/weekly_findings_$(date +%Y%m%d).md
   - Make targeted fixes if severity is CRITICAL or HIGH
4. Commit with message: "chore: weekly improvements from scout scan"
5. Create a draft PR:
   - Title: "chore: weekly improvements - $(date +%A)"
   - Body template:
     ```
     ## Weekly Improvement Scan
     
     Automated improvement suggestions from continuous monitoring.
     
     ### Findings Summary
     (Auto-populated from findings.json)
     
     - CRITICAL items: [N] (blocking)
     - HIGH items: [N] (important)
     - MEDIUM items: [N] (nice-to-have)
     
     ### Context Read
     - ✓ skills/ (manifesto-aligned patterns)
     - ✓ agents/projects/ (orchestration state)
     - ✓ workflows/ (topology, Express targets)
     
     ## Review Checklist
     - [ ] Findings align with MANIFESTO.md principles
     - [ ] No secrets exposed
     - [ ] Code follows repo conventions
     - [ ] Tests pass (if code changes)
     ```
6. Do NOT merge—leave as draft for human review.

## Success Criteria
- ✓ Draft PR created and ready for review
- ✓ All findings documented
- ✓ No secrets or raw dumps exposed
- ✓ Changes cite evidence (paths, timestamps)
"""
    return task

def run_claude_orchestration(task):
    """Delegate to local Claude Code in print mode"""
    print(f"[{datetime.now().isoformat()}] Delegating to local Claude Code...")
    
    # Use Claude Code in print mode for structured, non-interactive workflow
    cmd = [
        CLAUDE_BIN,
        "-p",
        task,
        "--max-turns", "15",
        "--max-budget-usd", "2.00",
        "--allowedTools", "Read,Write,Edit,Bash",
        "--model", "sonnet",
    ]
    
    result = subprocess.run(
        cmd,
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        timeout=600,  # 10 min max
    )
    
    if result.returncode != 0:
        print(f"Claude Code failed:\n{result.stderr}")
        sys.exit(1)
    
    print(f"Claude output:\n{result.stdout}")
    return result.stdout

def verify_pr_created():
    """Check that a draft PR was created"""
    print(f"[{datetime.now().isoformat()}] Verifying PR creation...")
    
    result = subprocess.run(
        ["gh", "pr", "list", "--state", "open", "--limit", "1"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        timeout=30,
    )
    
    if "feat/weekly-improvements" in result.stdout:
        print("✓ Draft PR created successfully")
        return True
    else:
        print("⚠ Could not verify PR creation (gh command may not be available)")
        return False

if __name__ == "__main__":
    os.chdir(REPO_ROOT)
    
    print(f"=== HARQIS Weekly Improvement Orchestration ===")
    print(f"Start: {datetime.now().isoformat()}")
    print(f"Repo: {REPO_ROOT}")
    print()
    
    # 1. Run scout
    findings = run_improvement_scout()
    
    # 2. Prepare task for Claude
    task = prepare_claude_task(findings)
    
    # 3. Delegate to Claude Code
    output = run_claude_orchestration(task)
    
    # 4. Verify
    verify_pr_created()
    
    print()
    print(f"End: {datetime.now().isoformat()}")
    print("✓ Weekly orchestration complete. Check GitHub for draft PR.")
