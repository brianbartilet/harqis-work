#!/usr/bin/env bash
# run_workflow_scheduler.sh — Start the Celery Beat scheduler.
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/set_env_workflows.sh"

cd "$ROOT_DIRECTORY"

echo "Starting scheduler..."
python run_workflows.py scheduler
