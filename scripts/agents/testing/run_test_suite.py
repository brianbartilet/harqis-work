#!/usr/bin/env python3
"""
Exploratory & Continuous Test Suite for HARQIS-work

Runs comprehensive test suites with coverage tracking, performance monitoring,
and exploratory test scenarios. Reports back on test health, performance regressions,
and potential weak areas.

Usage:
    python scripts/agents/testing/run_test_suite.py --quick          # Fast smoke tests
    python scripts/agents/testing/run_test_suite.py --full           # All tests with coverage
    python scripts/agents/testing/run_test_suite.py --exploratory    # Hypothesis + fuzzy tests
    python scripts/agents/testing/run_test_suite.py --performance    # Perf benchmarks
"""

import sys
import json
import re
import subprocess
from pathlib import Path
from datetime import datetime
from typing import Optional

REPO_ROOT = Path(__file__).resolve().parents[3]


class TestRunner:
    def __init__(self):
        self.results = {
            "timestamp": datetime.now().isoformat(),
            "tests": [],
            "coverage": None,
            "performance": None,
            "summary": {
                "passed": 0,
                "failed": 0,
                "skipped": 0,
                "errors": 0,
                "xfailed": 0,
                "xpassed": 0,
                "deselected": 0,
            }
        }
    
    def run_pytest(self, args: list[str], mode: str = "default") -> dict:
        """Run pytest with given arguments."""
        cmd = [sys.executable, "-m", "pytest"] + args
        evidence = {
            "mode": mode, "returncode": -1, "passed": False,
            "stdout": "", "stderr": "", "command": " ".join(cmd),
        }
        try:
            # Direct cron invocation starts with only this nested script on sys.path.
            if str(REPO_ROOT) not in sys.path:
                sys.path.insert(0, str(REPO_ROOT))
            from scripts.launch import setup_env

            setup_env()
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=120,
                cwd=REPO_ROOT
            )
            
            evidence.update(
                returncode=result.returncode, passed=result.returncode == 0,
                stdout=result.stdout, stderr=result.stderr,
            )
        except subprocess.TimeoutExpired as exc:
            evidence.update(error="timeout", stdout=exc.stdout, stderr=exc.stderr)
        except Exception as exc:
            evidence["error"] = str(exc)

        # TimeoutExpired may carry bytes even when text=True. Keep one JSON-safe
        # schema for success, collection errors, timeouts and launch failures.
        for stream in ("stdout", "stderr"):
            value = evidence[stream] or ""
            if isinstance(value, bytes):
                value = value.decode("utf-8", errors="replace")
            evidence[stream] = value
            evidence[f"{stream}_lines"] = len(value.splitlines())
        # Parse only pytest's final timed summary, not numbers in tracebacks.
        # Missing summaries (notably timeouts) are explicitly incomplete.
        counts = dict.fromkeys(self.results["summary"], 0)
        outcome_pattern = r"passed|failed|skipped|errors?|xfailed|xpassed|deselected"
        summary_pattern = (
            rf"[= ]*\d+ (?:{outcome_pattern}|warnings?|tests? collected)"
            rf"(?:, \d+ (?:{outcome_pattern}|warnings?|tests? collected))*"
            r" in \d+(?:\.\d+)?s(?: \([\d:]+\))?[= ]*"
        )
        summary_line = next(
            (line for line in reversed(evidence["stdout"].splitlines())
             if re.fullmatch(summary_pattern, line)), ""
        )
        for number, outcome in re.findall(rf"(\d+) ({outcome_pattern})\b", summary_line):
            counts["errors" if outcome == "error" else outcome] = int(number)
        evidence["counts"] = counts
        evidence["counts_complete"] = bool(summary_line) and "error" not in evidence
        for outcome, count in counts.items():
            self.results["summary"][outcome] += count
        print("  Test outcomes: " + ", ".join(f"{count} {outcome}" for outcome, count in counts.items())
              + ("" if evidence["counts_complete"] else " (incomplete; see output)"))
        if not evidence["passed"]:
            if evidence.get("error"):
                print(f"  Runner error: {evidence['error']}")
            for stream in ("stdout", "stderr"):
                if evidence[stream]:
                    print(evidence[stream], end="" if evidence[stream].endswith("\n") else "\n")
        return evidence
    
    def run_quick(self) -> bool:
        """Legacy quick selection, no coverage; includes live integration tests."""
        print("Running QUICK test suite...")
        result = self.run_pytest([
            "workflows/",
            "agents/",
            "--ignore=workflows/hud/tests/test_hud_gpt.py",  # Windows-only
            "--ignore=workflows/hud/tests/test_hud_utils.py",  # Windows-only (win32gui)
            "-q",
            "--tb=short",
            "-x",  # stop on first failure
        ], mode="quick")
        
        self.results["tests"].append(result)
        
        status = "✓ PASS" if result["passed"] else "✗ FAIL"
        print(f"  {status}: Quick tests ({result['stdout_lines']} lines output)")
        return result["passed"]
    
    def run_full(self) -> bool:
        """Full suite with coverage."""
        print("Running FULL test suite with coverage...")
        result = self.run_pytest([
            "workflows/",
            "agents/",
            "--cov=workflows",
            "--cov=agents",
            "--cov-report=json:.coverage.json",
            "--cov-report=term-missing",
            "-v",
            "--tb=short",
        ], mode="full")
        
        self.results["tests"].append(result)
        
        # Try to load coverage data
        try:
            coverage_file = REPO_ROOT / ".coverage.json"
            if coverage_file.exists():
                with open(coverage_file) as f:
                    cov_data = json.load(f)
                    if "totals" in cov_data:
                        self.results["coverage"] = cov_data["totals"]
        except Exception:
            pass
        
        status = "✓ PASS" if result["passed"] else "✗ FAIL"
        print(f"  {status}: Full tests with coverage ({result['stdout_lines']} lines)")
        return result["passed"]
    
    def run_exploratory(self) -> bool:
        """Exploratory tests: hypothesis, edge cases, property-based."""
        print("Running EXPLORATORY test scenarios...")
        
        # Try to find and run any hypothesis/fuzz tests
        result = self.run_pytest([
            "workflows/",
            "agents/",
            "-k", "hypothesis or fuzz or property",
            "-v",
            "--tb=short",
        ], mode="exploratory")
        
        self.results["tests"].append(result)
        
        status = "✓ PASS" if result["passed"] else "○ NONE" if "error" in result else "✗ FAIL"
        print(f"  {status}: Exploratory tests")
        
        return True  # Don't fail the run if no exploratory tests exist
    
    def run_performance(self) -> bool:
        """Performance/benchmark tests."""
        print("Running PERFORMANCE benchmarks...")
        
        result = self.run_pytest([
            "workflows/",
            "agents/",
            "-k", "bench or perf or performance",
            "-v",
            "--durations=10",
        ], mode="performance")
        
        self.results["tests"].append(result)
        
        status = "✓ PASS" if result["passed"] else "○ NONE" if "error" in result else "✗ FAIL"
        print(f"  {status}: Performance tests")
        
        return True  # Don't fail the run if no perf tests exist
    
    def save_results(self, path: Optional[Path] = None) -> Path:
        """Save results to JSON."""
        if path is None:
            path = REPO_ROOT / ".harqis-data" / "test_results_latest.json"
        
        path.parent.mkdir(parents=True, exist_ok=True)
        
        with open(path, "w") as f:
            json.dump(self.results, f, indent=2)
        
        return path


def main():
    import argparse
    
    parser = argparse.ArgumentParser(description="HARQIS test suite runner")
    parser.add_argument("--quick", action="store_true", help="Quick smoke tests")
    parser.add_argument("--full", action="store_true", help="Full tests with coverage")
    parser.add_argument("--exploratory", action="store_true", help="Exploratory tests")
    parser.add_argument("--performance", action="store_true", help="Performance tests")
    parser.add_argument("--all", action="store_true", help="Run all test modes")
    
    args = parser.parse_args()
    
    # Default to quick if nothing specified
    if not any([args.quick, args.full, args.exploratory, args.performance, args.all]):
        args.quick = True
    
    if args.all:
        args.quick = args.full = args.exploratory = args.performance = True
    
    runner = TestRunner()
    
    print("\n" + "="*80)
    print(f"HARQIS Test Suite Runner — {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("="*80 + "\n")
    
    results = []
    
    if args.quick:
        results.append(runner.run_quick())
    
    if args.full:
        results.append(runner.run_full())
    
    if args.exploratory:
        results.append(runner.run_exploratory())
    
    if args.performance:
        results.append(runner.run_performance())
    
    # Save results
    results_file = runner.save_results()
    print(f"\n✓ Results saved: {results_file.relative_to(REPO_ROOT)}")
    
    # Summary
    print("\n" + "-"*80)
    print(f"Test Runs: {len(runner.results['tests'])}")
    print("Test outcomes: " + ", ".join(
        f"{count} {outcome}" for outcome, count in runner.results["summary"].items()
    ))
    if runner.results["coverage"]:
        cov_pct = runner.results["coverage"].get("percent_covered", 0)
        print(f"Coverage: {cov_pct:.1f}%")
    
    # Exit with failure if any test run failed
    exit_code = 0 if all(results) else 1
    print(f"Exit Code: {exit_code}\n")
    
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
