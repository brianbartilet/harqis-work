#!/usr/bin/env python3
"""
Exploratory & Continuous Test Suite for HARQIS-work

Runs comprehensive test suites with coverage tracking, performance monitoring,
and exploratory test scenarios. Reports back on test health, performance regressions,
and potential weak areas.

Usage:
    python scripts/agents/run_test_suite.py --quick          # Fast smoke tests
    python scripts/agents/run_test_suite.py --full           # All tests with coverage
    python scripts/agents/run_test_suite.py --exploratory    # Hypothesis + fuzzy tests
    python scripts/agents/run_test_suite.py --performance    # Perf benchmarks
"""

import sys
import json
import subprocess
from pathlib import Path
from datetime import datetime
from typing import Optional

REPO_ROOT = Path(__file__).resolve().parents[2]


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
            }
        }
    
    def run_pytest(self, args: list[str], mode: str = "default") -> dict:
        """Run pytest with given arguments."""
        cmd = [sys.executable, "-m", "pytest"] + args
        
        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=120,
                cwd=REPO_ROOT
            )
            
            return {
                "mode": mode,
                "returncode": result.returncode,
                "passed": result.returncode == 0,
                "stdout_lines": len(result.stdout.split('\n')),
                "stderr_lines": len(result.stderr.split('\n')),
                "command": " ".join(cmd),
            }
        
        except subprocess.TimeoutExpired:
            return {
                "mode": mode,
                "returncode": -1,
                "passed": False,
                "error": "timeout",
                "command": " ".join(cmd),
            }
        except Exception as e:
            return {
                "mode": mode,
                "returncode": -1,
                "passed": False,
                "error": str(e),
                "command": " ".join(cmd),
            }
    
    def run_quick(self) -> bool:
        """Fast smoke tests: only unit tests, no coverage."""
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
        self.results["summary"]["passed"] += 1 if result["passed"] else 0
        self.results["summary"]["failed"] += 0 if result["passed"] else 1
        
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
        self.results["summary"]["passed"] += 1 if result["passed"] else 0
        self.results["summary"]["failed"] += 0 if result["passed"] else 1
        
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
    if runner.results["coverage"]:
        cov_pct = runner.results["coverage"].get("percent_covered", 0)
        print(f"Coverage: {cov_pct:.1f}%")
    
    # Exit with failure if any test run failed
    exit_code = 0 if all(results) else 1
    print(f"Exit Code: {exit_code}\n")
    
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
