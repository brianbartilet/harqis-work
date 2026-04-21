#!/usr/bin/env bash
# run_workflow_worker_hud.sh — Start a Celery worker on the hud queue.
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/set_env_workflows.sh"

cd "$ROOT_DIRECTORY"

export WORKFLOW_QUEUE="hud"

echo "Starting worker (queue: $WORKFLOW_QUEUE)..."
python run_workflows.py worker
