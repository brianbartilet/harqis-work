#!/usr/bin/env bash
# Daemon wrapper for the FastAPI frontend — called by LaunchAgent.
set -euo pipefail

REPO_ROOT="$(git -C "$(dirname "$0")" rev-parse --show-toplevel)"
export PYTHONPATH="${PYTHONPATH:-}:$REPO_ROOT/frontend"

source "$REPO_ROOT/.venv/bin/activate"

# Load env file so FastAPI settings are available
ENV_FILE="$REPO_ROOT/.env/apps.env"
if [ -f "$ENV_FILE" ]; then
  while IFS= read -r line || [ -n "$line" ]; do
    [[ -z "$line" || "$line" == \#* || "$line" != *=* ]] && continue
    key="${line%%=*}"
    value="${line#*=}"
    value="${value%\"}" ; value="${value#\"}"
    value="${value%\'}" ; value="${value#\'}"
    export "$key=$value"
  done < "$ENV_FILE"
fi

exec python "$REPO_ROOT/frontend/main.py"
