#!/usr/bin/env python3
"""
HARQIS Environment Health Check

Quick diagnostics for environment, dependencies, and configuration.
Produces JSON report safe to log and analyze.
"""

import os
import sys
import json
import subprocess
from pathlib import Path
from datetime import datetime

REPO_ROOT = Path(__file__).resolve().parent.parent
ENV_DIR = REPO_ROOT / ".env"


def check_env_files():
    """Verify .env directory structure."""
    checks = {}
    
    for required_file in ["apps.env", ".env.nodes"]:
        path = ENV_DIR / required_file
        checks[required_file] = {
            "exists": path.exists(),
            "readable": path.exists() and os.access(path, os.R_OK),
            "size_bytes": path.stat().st_size if path.exists() else 0,
        }
    
    return checks


def check_python_deps():
    """Verify critical Python dependencies."""
    checks = {}
    
    required_modules = [
        "anthropic",
        "celery",
        "flask",
        "pytest",
        "dotenv",
    ]
    
    for module in required_modules:
        try:
            __import__(module)
            checks[module] = {"available": True}
        except ImportError as e:
            checks[module] = {"available": False, "error": str(e)}
    
    return checks


def check_venv():
    """Check virtual environment state."""
    venv_path = REPO_ROOT / ".venv"
    python_exe = venv_path / "bin" / "python"
    
    return {
        "venv_exists": venv_path.exists(),
        "python_exe_exists": python_exe.exists(),
        "using_venv": sys.prefix != sys.base_prefix,
        "python_version": f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}",
    }


def check_git_status():
    """Quick git repo health."""
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            capture_output=True,
            text=True,
            timeout=5,
            cwd=REPO_ROOT
        )
        
        current_commit = result.stdout.strip() if result.returncode == 0 else None
        
        # Check for uncommitted changes
        result = subprocess.run(
            ["git", "status", "--porcelain"],
            capture_output=True,
            text=True,
            timeout=5,
            cwd=REPO_ROOT
        )
        
        dirty_files = len([l for l in result.stdout.split('\n') if l.strip()])
        
        return {
            "is_git_repo": True,
            "current_commit": current_commit,
            "dirty_files": dirty_files,
        }
    except Exception as e:
        return {
            "is_git_repo": False,
            "error": str(e),
        }


def check_services():
    """Check if required services are running (basic checks)."""
    checks = {}
    
    # Check if Redis is accessible (needed for Celery)
    try:
        import redis
        r = redis.Redis(host='localhost', port=6379, socket_connect_timeout=2)
        r.ping()
        checks["redis"] = {"available": True}
    except Exception as e:
        checks["redis"] = {"available": False, "error": type(e).__name__}
    
    return checks


def main():
    """Run all checks and output JSON."""
    report = {
        "timestamp": datetime.now().isoformat(),
        "repo": str(REPO_ROOT),
        "checks": {
            "env_files": check_env_files(),
            "python_deps": check_python_deps(),
            "venv": check_venv(),
            "git": check_git_status(),
            "services": check_services(),
        }
    }
    
    # Calculate overall health
    all_ok = True
    for category, checks_dict in report["checks"].items():
        if isinstance(checks_dict, dict):
            for key, status in checks_dict.items():
                if isinstance(status, dict):
                    if status.get("available") is False:
                        all_ok = False
                    elif status.get("exists") is False:
                        all_ok = False
    
    report["overall_health"] = "ok" if all_ok else "warning"
    
    print(json.dumps(report, indent=2))
    return 0 if all_ok else 1


if __name__ == "__main__":
    sys.exit(main())
