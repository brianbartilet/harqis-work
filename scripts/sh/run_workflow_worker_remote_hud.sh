#!/usr/bin/env bash
# run_workflow_worker_remote_hud.sh — Start the HUD queue worker on a remote node.
# Config is fetched from the host (Redis or HTTP) — no local apps.env needed.
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/set_env_worker_remote.sh"

cd "$ROOT_DIRECTORY"

export WORKFLOW_QUEUE="hud"

echo "Starting remote worker (queue: $WORKFLOW_QUEUE, config: $CONFIG_SOURCE)..."
python run_workflows.py worker
