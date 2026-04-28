#!/usr/bin/env bash
# run_config_server.sh — Resolve local config and serve it over HTTP.
#
# Run this on the HOST MACHINE. Remote workers with CONFIG_SOURCE=http will
# fetch config from this server at startup via GET /config.
#
# The server stays running; stop it with Ctrl-C or by killing the process.
#
# Usage:
#   bash scripts/sh/run_config_server.sh
#   bash scripts/sh/run_config_server.sh --port 8765 --token mysecrettoken
#
# Required env vars (set before calling, or export in .env/apps.env):
#   CONFIG_SERVER_TOKEN  Bearer token workers must present (recommended)
#   CONFIG_SERVER_PORT   Port to listen on  (default: 8765)
#
# The CELERY_BROKER_URL exported here is the address visible to REMOTE workers.
# Set REMOTE_BROKER_URL to the host's VPN/network address before running, or
# edit the default below.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

source "$SCRIPT_DIR/set_env_workflows.sh"

cd "$ROOT_DIRECTORY"

# Override broker URL to the address reachable from remote workers.
export CELERY_BROKER_URL="${REMOTE_BROKER_URL:-${CELERY_BROKER_URL}}"

echo ""
echo "Starting config HTTP server..."
echo "  CONFIG_SERVER_PORT  : ${CONFIG_SERVER_PORT:-8765}"
echo "  CONFIG_SERVER_TOKEN : ${CONFIG_SERVER_TOKEN:-(none — open access)}"
echo "  CELERY_BROKER_URL   : $CELERY_BROKER_URL"
echo ""

python -m apps.config_remote serve-http "$@"
