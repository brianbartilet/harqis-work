#!/usr/bin/env bash
# set_env_worker_remote.sh — Configure environment for REMOTE worker nodes.
#
# Unlike set_env_workflows.sh, this script does NOT load apps.env or set
# PATH_APP_CONFIG. Config is fetched from the host at startup via Redis or HTTP.
#
# Source this script (don't execute it):
#   source scripts/sh/set_env_worker_remote.sh
#
# Required env vars — set these on the remote machine before sourcing:
#
#   CONFIG_SOURCE        redis | http
#   CELERY_BROKER_URL    amqp://guest:guest@<host-ip>:5672/
#
#   Redis mode:
#     CONFIG_REDIS_URL   redis://<host-ip>:6379/1
#     CONFIG_REDIS_KEY   (optional, default: harqis:config)
#
#   HTTP mode:
#     CONFIG_SERVER_URL    http://<host-ip>:8765
#     CONFIG_SERVER_TOKEN  (must match host server token)
#
# Tip: put these in .env/worker.env (see .env/worker.env.example) and this
# script will load them automatically.

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
path_git_root="$(git rev-parse --show-toplevel)"

echo "Git root: $path_git_root"

# ── Load minimal worker.env if present ───────────────────────────────────────
# worker.env holds only connection vars — NO application secrets.
WORKER_ENV_FILE="$path_git_root/.env/worker.env"
if [ -f "$WORKER_ENV_FILE" ]; then
    echo "Loading $WORKER_ENV_FILE..."
    while IFS= read -r line || [ -n "$line" ]; do
        [[ -z "$line" || "$line" == \#* || "$line" != *=* ]] && continue
        key="${line%%=*}"
        value="${line#*=}"
        value="${value%\"}" ; value="${value#\"}"
        value="${value%\'}" ; value="${value#\'}"
        export "$key=$value"
    done < "$WORKER_ENV_FILE"
fi

# ── Validate required vars ────────────────────────────────────────────────────
_fail() { echo "ERROR: $*" >&2; return 1 2>/dev/null || exit 1; }

[ -z "${CONFIG_SOURCE:-}" ]       && _fail "CONFIG_SOURCE must be 'redis' or 'http'"
[ -z "${CELERY_BROKER_URL:-}" ]   && _fail "CELERY_BROKER_URL must point to the host RabbitMQ"

if [ "$CONFIG_SOURCE" = "redis" ]; then
    [ -z "${CONFIG_REDIS_URL:-}" ] && _fail "CONFIG_REDIS_URL required when CONFIG_SOURCE=redis"
fi

if [ "$CONFIG_SOURCE" = "http" ]; then
    [ -z "${CONFIG_SERVER_URL:-}" ] && _fail "CONFIG_SERVER_URL required when CONFIG_SOURCE=http"
fi

# ── Python / workflow paths ───────────────────────────────────────────────────
export PYTHONPATH="$path_git_root:${PYTHONPATH:-}"
export ROOT_DIRECTORY="$path_git_root"
export WORKFLOW_CONFIG="workflows.config"
export APP_CONFIG_FILE="apps_config.yaml"

echo "CONFIG_SOURCE     = $CONFIG_SOURCE"
echo "CELERY_BROKER_URL = $CELERY_BROKER_URL"
echo "ROOT_DIRECTORY    = $ROOT_DIRECTORY"
echo "Remote worker environment ready."
