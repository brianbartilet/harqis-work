#!/usr/bin/env bash
# push_config.sh — Resolve local config and push the result to Redis.
#
# Run this on the HOST MACHINE whenever apps.env or apps_config.yaml changes.
# Remote workers with CONFIG_SOURCE=redis will pick up the new config on their
# next restart (the dict is fetched once at process startup).
#
# Usage:
#   bash scripts/sh/push_config.sh
#   bash scripts/sh/push_config.sh --redis-url redis://10.0.0.1:6379/1
#   bash scripts/sh/push_config.sh --redis-url redis://10.0.0.1:6379/1 --key mykey
#
# The CELERY_BROKER_URL exported here is the address visible to REMOTE workers,
# so it must be the host's network / VPN address (not localhost).
# Set it as an env var before calling this script, or edit the default below.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Load the full host environment (apps.env, PYTHONPATH, etc.)
source "$SCRIPT_DIR/set_env_workflows.sh"

cd "$ROOT_DIRECTORY"

# Override broker URL to the address reachable from remote workers.
# Default: use the WireGuard VPN host address. Adjust to match your topology.
export CELERY_BROKER_URL="${REMOTE_BROKER_URL:-${CELERY_BROKER_URL}}"

echo ""
echo "Pushing resolved config to Redis..."
echo "  CONFIG_REDIS_URL : ${CONFIG_REDIS_URL:-redis://localhost:6379/1}"
echo "  CONFIG_REDIS_KEY : ${CONFIG_REDIS_KEY:-harqis:config}"
echo "  CELERY_BROKER_URL: $CELERY_BROKER_URL"
echo ""

python -m apps.config_remote push-redis "$@"

echo ""
echo "Done. Remote workers will use the new config on next restart."
