#!/usr/bin/env bash
# Daemon wrapper for Celery Beat scheduler — called by LaunchAgent.
set -euo pipefail

REPO_ROOT="$(git -C "$(dirname "$0")" rev-parse --show-toplevel)"
export PYTHONPATH="${PYTHONPATH:-}"

source "$REPO_ROOT/.venv/bin/activate"
source "$REPO_ROOT/scripts/sh/set_env_workflows.sh"

exec python "$REPO_ROOT/run_workflows.py" scheduler
