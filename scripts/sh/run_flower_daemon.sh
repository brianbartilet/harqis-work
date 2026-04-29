#!/usr/bin/env bash
# Daemon wrapper for the Celery Flower monitoring UI — invoked by LaunchAgent / systemd.
#
# Env vars:
#   FLOWER_USER     — basic-auth username (required)
#   FLOWER_PASSWORD — basic-auth password (required)
#                     Legacy fallback: FLOWER_PASS is also accepted if FLOWER_PASSWORD is unset.
#   FLOWER_PORT     — TCP port (default: 5555)
#   FLOWER_ADDRESS  — bind address (default: 127.0.0.1; set 0.0.0.0 to expose over Tailscale)
set -euo pipefail

REPO_ROOT="$(git -C "$(dirname "$0")" rev-parse --show-toplevel)"
export PYTHONPATH="${PYTHONPATH:-}:$REPO_ROOT"

source "$REPO_ROOT/.venv/bin/activate"
source "$REPO_ROOT/scripts/sh/set_env_workflows.sh"

# Canonical name is FLOWER_PASSWORD (matches .env/apps.env). Fall back to FLOWER_PASS for legacy.
FLOWER_PASSWORD="${FLOWER_PASSWORD:-${FLOWER_PASS:-}}"
FLOWER_PORT="${FLOWER_PORT:-5555}"
FLOWER_ADDRESS="${FLOWER_ADDRESS:-127.0.0.1}"

if [ -z "${FLOWER_USER:-}" ] || [ -z "${FLOWER_PASSWORD:-}" ]; then
    echo "ERROR: FLOWER_USER and FLOWER_PASSWORD must be set in .env/apps.env" >&2
    exit 1
fi

echo "Starting Flower on $FLOWER_ADDRESS:$FLOWER_PORT (auth: $FLOWER_USER)"
exec python -m celery -A core.apps.sprout.app.celery:SPROUT flower \
    --port="$FLOWER_PORT" \
    --address="$FLOWER_ADDRESS" \
    --basic-auth="${FLOWER_USER}:${FLOWER_PASSWORD}"
