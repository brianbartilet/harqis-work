#!/usr/bin/env bash
# Daemon wrapper for a Celery worker — called by LaunchAgent / systemd.
#
# Env vars:
#   WORKFLOW_QUEUE — comma-separated queue list, e.g. "default" or "hud,tcg,default".
#                    Defaults to "default" if not set. Celery's -Q natively accepts
#                    multiple queues, so a single process listens to all of them.
set -euo pipefail

REPO_ROOT="$(git -C "$(dirname "$0")" rev-parse --show-toplevel)"
export PYTHONPATH="${PYTHONPATH:-}"
export WORKFLOW_QUEUE="${WORKFLOW_QUEUE:-default}"

source "$REPO_ROOT/.venv/bin/activate"
source "$REPO_ROOT/scripts/sh/set_env_workflows.sh"

echo "Starting worker on queue(s): $WORKFLOW_QUEUE"
exec python "$REPO_ROOT/run_workflows.py" worker
