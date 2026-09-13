#!/usr/bin/env python3
"""Bootstrap the monthly HFL archive in the repository Python environment.

Usage: .venv/bin/python -m scripts.agents.hfl.run_archive --root <corpus> --dry-run
Windows: .venv/Scripts/python.exe -m scripts.agents.hfl.run_archive --root <corpus> --dry-run
"""
from __future__ import annotations

import os
from pathlib import Path
import sys

REPO_ROOT = Path(__file__).resolve().parents[3]


def main():
    # Also support callers passing this script's absolute path from another cwd.
    sys.path.insert(0, str(REPO_ROOT))
    os.chdir(REPO_ROOT)
    from scripts.deploy import load_env_into_os, load_machine_config, machine_env_vars

    load_env_into_os()
    os.environ.setdefault('APP_CONFIG_FILE', str(REPO_ROOT / 'apps_config.yaml'))
    os.environ.setdefault('WORKFLOW_CONFIG', 'workflows.config')
    os.environ.update(machine_env_vars(load_machine_config(None)))
    from scripts.agents.hfl.archive_corpus import main as archive_main

    return archive_main()


if __name__ == '__main__':
    raise SystemExit(main())
