#!/usr/bin/env python3
"""
Daily HARQIS Improvement Scout

Comprehensive inspection system for HARQIS-work repository with focus on:
- Code quality & testing gaps
- Configuration & environment issues
- Workflow health & observability
- Integration status & coverage
- Performance & resource usage
- Documentation & manifesto compliance

Runs as a cron job, producing structured improvement recommendations.
Respects privacy constraints: no secrets, no raw dumps, only sanitized handles.
"""

import os
import sys
import json
import subprocess
from pathlib import Path
from datetime import datetime
from dataclasses import dataclass, asdict
from typing import Optional

REPO_ROOT = Path(__file__).resolve().parents[3]
ENV_DIR = REPO_ROOT / ".env"
SCRIPTS_DIR = REPO_ROOT / "scripts"

# ============================================================================
# Inspection Categories
# ============================================================================

@dataclass
class Finding:
    """A single inspection finding."""
    category: str  # e.g., "manifesto", "testing", "config", "workflow"
    severity: str  # info, warning, critical
    signal: str    # concise observation
    evidence: str  # source path/handle (sanitized)
    idea: str      # recommendation for improvement
    action: str    # smallest next step


class InspectionBatch:
    """Container for grouped findings."""
    
    def __init__(self):
        self.findings: list[Finding] = []
    
    def add(self, category: str, severity: str, signal: str, 
            evidence: str, idea: str, action: str):
        """Add a finding."""
        self.findings.append(Finding(
            category=category,
            severity=severity,
            signal=signal,
            evidence=evidence,
            idea=idea,
            action=action
        ))
    
    def to_dict(self):
        return {
            "timestamp": datetime.now().isoformat(),
            "findings": [asdict(f) for f in self.findings],
            "summary": {
                "total": len(self.findings),
                "by_category": self._count_by("category"),
                "by_severity": self._count_by("severity"),
            }
        }
    
    def _count_by(self, field: str) -> dict:
        counts = {}
        for finding in self.findings:
            key = getattr(finding, field)
            counts[key] = counts.get(key, 0) + 1
        return counts
    
    def report(self) -> str:
        """Generate human-readable report (sorted by severity)."""
        if not self.findings:
            return "No findings — all systems nominal."
        
        severity_order = {"critical": 0, "warning": 1, "info": 2}
        sorted_findings = sorted(
            self.findings, 
            key=lambda f: (severity_order.get(f.severity, 3), f.category)
        )
        
        lines = []
        lines.append(f"\n{'='*80}")
        lines.append(f"HARQIS Daily Improvement Scout — {datetime.now().strftime('%Y-%m-%d %H:%M')}")
        lines.append(f"{'='*80}\n")
        
        lines.append(f"Summary: {len(self.findings)} finding(s)")
        counts = self._count_by("severity")
        if counts:
            parts = [f"{k.upper()}: {v}" for k, v in sorted(counts.items())]
            lines.append(f"  {' | '.join(parts)}\n")
        
        current_severity = None
        current_category = None
        
        for finding in sorted_findings:
            # Severity break
            if finding.severity != current_severity:
                if current_severity is not None:
                    lines.append("")
                current_severity = finding.severity
                lines.append(f"\n[{finding.severity.upper()}]")
            
            # Category break
            if finding.category != current_category:
                current_category = finding.category
                lines.append(f"\n  {finding.category.title()}:")
            
            lines.append(f"    Signal: {finding.signal}")
            lines.append(f"    Evidence: {finding.evidence}")
            lines.append(f"    Idea: {finding.idea}")
            lines.append(f"    Next: {finding.action}")
            lines.append("")
        
        return "\n".join(lines)


# ============================================================================
# Inspection Functions
# ============================================================================

def inspect_manifesto_compliance(batch: InspectionBatch):
    """Check manifesto audit for violations and warnings."""
    try:
        result = subprocess.run(
            [sys.executable, SCRIPTS_DIR / "agents" / "repo-quality" / "manifesto_audit.py"],
            capture_output=True,
            text=True,
            timeout=10,
            cwd=REPO_ROOT
        )
        
        if result.returncode != 0:
            batch.add(
                "manifesto",
                "critical",
                "Manifesto audit failed or found hard violations",
                "scripts/agents/repo-quality/manifesto_audit.py",
                "Fix missing manifesto blocks in workflow entries",
                f"Run: python scripts/agents/repo-quality/manifesto_audit.py"
            )
        elif "FAIL" in result.stdout:
            # Extract violation count from output
            lines = result.stdout.split('\n')
            for line in lines:
                if "hard violation(s)" in line:
                    batch.add(
                        "manifesto",
                        "critical",
                        f"Manifesto compliance issues detected",
                        "workflows/ (check manifesto_audit output)",
                        "Ensure all run-job entries have proper manifesto blocks",
                        f"Run: python scripts/agents/repo-quality/manifesto_audit.py to see violations"
                    )
                    break
        
        if "soft warning(s)" in result.stdout:
            batch.add(
                "manifesto",
                "warning",
                "HFL activation warnings detected",
                "workflows/hfl/ (see manifesto audit)",
                "Verify HFL workflow activation state",
                "Check workflows/hfl/README.md for activation requirements"
            )
    
    except subprocess.TimeoutExpired:
        batch.add(
            "manifesto",
            "warning",
            "Manifesto audit timeout",
            "scripts/agents/repo-quality/manifesto_audit.py",
            "Audit may indicate processing bottleneck",
            "Run manually: python scripts/agents/repo-quality/manifesto_audit.py"
        )
    except Exception as e:
        batch.add(
            "manifesto",
            "warning",
            f"Manifesto audit error: {type(e).__name__}",
            "scripts/agents/repo-quality/manifesto_audit.py",
            "Unable to verify compliance",
            "Check if script is executable and dependencies installed"
        )


def inspect_test_coverage(batch: InspectionBatch):
    """Scan for untested or minimally tested modules."""
    test_dirs = list(REPO_ROOT.glob("workflows/*/tests"))
    
    if not test_dirs:
        batch.add(
            "testing",
            "warning",
            "No test directories found in workflows",
            "workflows/",
            "Establish baseline test coverage structure",
            "Create tests/ dirs in major workflow modules"
        )
        return
    
    test_count = sum(len(list(d.glob("*.py"))) for d in test_dirs)
    
    if test_count < 10:
        batch.add(
            "testing",
            "warning",
            f"Low test count ({test_count} test files across workflows)",
            "workflows/*/tests/",
            "Expand test coverage for critical workflows",
            "Identify untested workflows and add baseline test suites"
        )
    
    # Check for workflows without tests
    workflow_dirs = [d for d in (REPO_ROOT / "workflows").iterdir() 
                     if d.is_dir() and not d.name.startswith((".template", "__"))]
    workflows_without_tests = [d.name for d in workflow_dirs 
                               if not (d / "tests").exists()]
    
    if workflows_without_tests:
        batch.add(
            "testing",
            "info",
            f"Workflows without test directories: {len(workflows_without_tests)}",
            f"workflows/: {', '.join(workflows_without_tests[:3])}{'...' if len(workflows_without_tests) > 3 else ''}",
            "Add test infrastructure to untested workflows",
            f"Start with: workflows/{workflows_without_tests[0]}/tests/"
        )


def inspect_environment_config(batch: InspectionBatch):
    """Check environment file consistency and config coverage."""
    apps_env = ENV_DIR / "apps.env"
    
    if not apps_env.exists():
        batch.add(
            "config",
            "critical",
            "apps.env configuration missing",
            f".env/apps.env",
            "Create or restore apps.env with required integrations",
            f"Check .env/apps.env.nodes for reference"
        )
        return
    
    try:
        # Count configured apps
        with open(apps_env) as f:
            lines = f.readlines()
        
        enabled_apps = [l for l in lines if l.strip() and not l.startswith("#")]
        
        if len(enabled_apps) < 10:
            batch.add(
                "config",
                "info",
                f"Minimal app configuration ({len(enabled_apps)} entries)",
                ".env/apps.env",
                "Verify all required integrations are configured",
                "Review apps_config.yaml for reference integrations"
            )
    
    except Exception as e:
        batch.add(
            "config",
            "warning",
            f"Could not parse apps.env: {type(e).__name__}",
            ".env/apps.env",
            "Verify configuration file integrity",
            "Check file encoding and format"
        )


def inspect_workflow_health(batch: InspectionBatch):
    """Check workflow readiness and dependencies."""
    # Check for README.md in major workflow dirs
    major_workflows = ["hfl", "knowledge", "desktop", "hud"]
    
    for workflow_name in major_workflows:
        workflow_path = REPO_ROOT / "workflows" / workflow_name
        readme_path = workflow_path / "README.md"
        
        if not readme_path.exists():
            batch.add(
                "workflow",
                "warning",
                f"Workflow missing documentation",
                f"workflows/{workflow_name}/",
                f"Add README.md documenting activation, data flow, and Express outputs",
                f"Use workflows/hfl/README.md as template reference"
            )
        else:
            # Check if README mentions activation state
            try:
                with open(readme_path) as f:
                    content = f.read().lower()
                if "activation" not in content and "active" not in content:
                    batch.add(
                        "workflow",
                        "info",
                        f"Workflow README lacks activation guidance",
                        f"workflows/{workflow_name}/README.md",
                        "Document activation requirements and current state",
                        f"Add 'Activation' section to README"
                    )
            except Exception:
                pass


def inspect_mcp_sync(batch: InspectionBatch):
    """Check MCP server registration and tool inventory."""
    try:
        result = subprocess.run(
            ["hermes", "mcp", "list"],
            capture_output=True,
            text=True,
            timeout=5
        )
        
        if "harqis-work" not in result.stdout:
            batch.add(
                "mcp",
                "warning",
                "HARQIS-work MCP server not registered with Hermes",
                "hermes mcp list",
                "Register HARQIS-work MCP to enable Elasticsearch/app access",
                "Run: python scripts/deploy.py --restart mcp"
            )
    
    except Exception:
        # Hermes not available in this context, skip
        pass


def inspect_git_status(batch: InspectionBatch):
    """Check git repo status for uncommitted changes."""
    try:
        result = subprocess.run(
            ["git", "status", "--porcelain"],
            capture_output=True,
            text=True,
            timeout=5,
            cwd=REPO_ROOT
        )
        
        if result.returncode == 0 and result.stdout.strip():
            line_count = len([l for l in result.stdout.split('\n') if l.strip()])
            if line_count > 5:
                batch.add(
                    "repo",
                    "info",
                    f"Uncommitted changes detected ({line_count} modified files)",
                    "git status",
                    "Review and commit progress or stash experimental work",
                    "Run: git status for details"
                )
    
    except Exception:
        pass


def inspect_dependency_lock(batch: InspectionBatch):
    """Check for outdated or missing dependency locks."""
    requirements_files = list(REPO_ROOT.glob("*requirements*.txt"))
    pyproject = REPO_ROOT / "pyproject.toml"
    poetry_lock = REPO_ROOT / "poetry.lock"
    
    if not requirements_files and not pyproject:
        batch.add(
            "deps",
            "warning",
            "No dependency specification found",
            "root",
            "Establish dependency lock strategy (requirements.txt or poetry.lock)",
            "Choose and configure dependency management tool"
        )
    elif pyproject.exists() and not poetry_lock.exists():
        batch.add(
            "deps",
            "info",
            "pyproject.toml present but no poetry.lock",
            "pyproject.toml / poetry.lock",
            "Use poetry lock to pin reproducible builds",
            "Run: poetry lock (if poetry is configured)"
        )


def inspect_documentation(batch: InspectionBatch):
    """Check docs/ coverage and age."""
    docs_dir = REPO_ROOT / "docs"
    
    if not docs_dir.exists():
        batch.add(
            "docs",
            "warning",
            "No docs/ directory found",
            "root/docs/",
            "Create documentation structure for reference and onboarding",
            "Create docs/ with MANIFESTO.md, ARCHITECTURE.md, and info/"
        )
        return
    
    required_docs = ["MANIFESTO.md", "ARCHITECTURE.md"]
    missing_docs = [f for f in required_docs if not (docs_dir / f).exists()]
    
    if missing_docs:
        batch.add(
            "docs",
            "warning",
            f"Core documentation missing: {', '.join(missing_docs)}",
            f"docs/",
            "Document architecture and operating principles",
            f"Create: docs/{missing_docs[0]}"
        )


def inspect_docker_health(batch: InspectionBatch):
    """Check Docker Compose configuration."""
    compose_file = REPO_ROOT / "docker-compose.yml"
    
    if not compose_file.exists():
        batch.add(
            "infra",
            "info",
            "No docker-compose.yml found",
            "root/",
            "Consider containerization for reproducible local dev/prod",
            "Optional: create docker-compose.yml for services"
        )
        return
    
    try:
        with open(compose_file) as f:
            content = f.read()
        
        if "redis" not in content.lower():
            batch.add(
                "infra",
                "info",
                "Redis not in docker-compose (required for Celery)",
                "docker-compose.yml",
                "Verify Redis connectivity for queue workers",
                "Check: docker compose ps"
            )
    except Exception:
        pass


def inspect_performance_hints(batch: InspectionBatch):
    """Look for obvious performance/resource patterns."""
    # Check for large logging or dumping patterns
    try:
        result = subprocess.run(
            ["find", str(REPO_ROOT / "workflows"), "-name", "*.py", "-type", "f"],
            capture_output=True,
            text=True,
            timeout=5
        )
        
        py_files = result.stdout.strip().split('\n')
        
        # Quick heuristic: count files with excessive logging patterns
        high_logging_files = []
        for py_file in py_files[:20]:  # Sample
            try:
                with open(py_file, errors="ignore") as f:
                    content = f.read()
                if content.count("print(") > 10 or content.count("logger.") > 20:
                    high_logging_files.append(Path(py_file).relative_to(REPO_ROOT))
            except:
                pass
        
        if high_logging_files:
            batch.add(
                "performance",
                "info",
                f"High logging volume in {len(high_logging_files)} sampled files",
                f"workflows/ ({high_logging_files[0] if high_logging_files else 'see scan'})",
                "Review logging verbosity for production efficiency",
                "Audit log levels and reduce unnecessary output"
            )
    except Exception:
        pass


def inspect_secrets_exposure(batch: InspectionBatch):
    """Quick sanity check: no obvious secrets in tracked files."""
    try:
        result = subprocess.run(
            ["git", "grep", "-i", "password\\|secret\\|key\\|token"],
            capture_output=True,
            text=True,
            timeout=5,
            cwd=REPO_ROOT
        )
        
        if result.returncode == 0 and result.stdout.strip():
            # Only alert if matches are outside .env or docs
            lines = result.stdout.split('\n')
            suspicious = [l for l in lines 
                         if l and not any(x in l for x in [".env", "docs/", ".gitignore", "example", "sample"])]
            
            if suspicious:
                batch.add(
                    "security",
                    "critical",
                    f"Potential secrets found in tracked files",
                    "git grep (see git log for diffs)",
                    "Rotate and remove all exposed credentials immediately",
                    "Run: git log -p to find and purge commits"
                )
    except Exception:
        pass


# ============================================================================
# Main
# ============================================================================

def main():
    """Run all inspections and generate report."""
    batch = InspectionBatch()
    
    # Run all inspection functions
    inspect_manifesto_compliance(batch)
    inspect_test_coverage(batch)
    inspect_environment_config(batch)
    inspect_workflow_health(batch)
    inspect_mcp_sync(batch)
    inspect_git_status(batch)
    inspect_dependency_lock(batch)
    inspect_documentation(batch)
    inspect_docker_health(batch)
    inspect_performance_hints(batch)
    inspect_secrets_exposure(batch)
    
    # Output human-readable report
    print(batch.report())
    
    # Also save structured JSON for programmatic use
    json_file = REPO_ROOT / ".harqis-data" / "improvement_scout_latest.json"
    json_file.parent.mkdir(parents=True, exist_ok=True)
    
    try:
        with open(json_file, "w") as f:
            json.dump(batch.to_dict(), f, indent=2)
        print(f"\nStructured data saved: {json_file.relative_to(REPO_ROOT)}")
    except Exception as e:
        print(f"\nWarning: could not save JSON: {e}")
    
    return 0 if not any(f.severity == "critical" for f in batch.findings) else 1


if __name__ == "__main__":
    sys.exit(main())
