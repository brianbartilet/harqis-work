#!/usr/bin/env bash
# set_env_workflows.sh — Load app env vars and configure Python paths.
# Source this script (don't run it): source scripts/linux/set_env_workflows.sh

# ── Resolve paths ─────────────────────────────────────────────────────────────
path_git_root=$(git rev-parse --show-toplevel)
path_script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

echo "Git root detected: $path_git_root"

# ── Load .env/apps.env ────────────────────────────────────────────────────────
ENV_FILE="$path_git_root/.env/apps.env"

if [ -f "$ENV_FILE" ]; then
    echo "Loading env vars from \"$ENV_FILE\"..."
    while IFS= read -r line || [ -n "$line" ]; do
        # Skip blank lines and comments
        [[ -z "$line" || "$line" == \#* ]] && continue
        # Skip lines without =
        [[ "$line" != *=* ]] && continue
        key="${line%%=*}"
        value="${line#*=}"
        # Strip surrounding quotes if present
        value="${value%\"}"
        value="${value#\"}"
        value="${value%\'}"
        value="${value#\'}"
        export "$key=$value"
    done < "$ENV_FILE"
else
    echo "WARNING: .env file not found at \"$ENV_FILE\""
fi

# ── Python path ───────────────────────────────────────────────────────────────
echo "Updating PYTHONPATH..."
export PYTHONPATH="$path_git_root:$path_script_dir:$PYTHONPATH"
echo "PYTHONPATH updated to $PYTHONPATH"

# ── Application paths ─────────────────────────────────────────────────────────
export ROOT_DIRECTORY="$path_git_root"
export PATH_APP_CONFIG="$path_git_root"
export PATH_APP_CONFIG_SECRETS="$path_git_root/.env"

# ── Celery / Sprout config ────────────────────────────────────────────────────
export WORKFLOW_CONFIG="workflows.config"
echo "WORKFLOW_CONFIG set to $WORKFLOW_CONFIG"

export APP_CONFIG_FILE="apps_config.yaml"
echo "APP_CONFIG_FILE set to $APP_CONFIG_FILE"
