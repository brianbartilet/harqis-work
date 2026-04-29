#!/usr/bin/env bash
# Daemon wrapper for the harqis-work MCP server.
#
# Note: the MCP server speaks stdio to its client (typically Claude Desktop spawns
# this process directly). This wrapper exists for two cases:
#   1. SSH remote access — `ssh host /opt/harqis/scripts/sh/run_mcp_daemon.sh`
#   2. HTTP transport (when configured upstream) under launchd / systemd
set -euo pipefail

REPO_ROOT="$(git -C "$(dirname "$0")" rev-parse --show-toplevel)"
export PYTHONPATH="${PYTHONPATH:-}:$REPO_ROOT"

source "$REPO_ROOT/.venv/bin/activate"

# Ensure the production config file is used regardless of ENV setting
export APP_CONFIG_FILE="${APP_CONFIG_FILE:-apps_config.yaml}"

exec python "$REPO_ROOT/mcp/server.py"
