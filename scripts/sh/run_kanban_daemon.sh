#!/usr/bin/env bash
# Daemon wrapper for the Kanban orchestrator — called by LaunchAgent / systemd.
#
# Env vars:
#   KANBAN_NUM_AGENTS   — concurrent in-process agent workers (default: 1)
#   KANBAN_POLL_INTERVAL — seconds between board polls (default: orchestrator default)
#   KANBAN_PROFILES_DIR — override profiles directory
#   KANBAN_DRY_RUN      — set to "1" to log actions without invoking Claude
set -euo pipefail

REPO_ROOT="$(git -C "$(dirname "$0")" rev-parse --show-toplevel)"
export PYTHONPATH="${PYTHONPATH:-}:$REPO_ROOT"

source "$REPO_ROOT/.venv/bin/activate"
source "$REPO_ROOT/scripts/sh/set_env_workflows.sh"

ARGS=()
[ -n "${KANBAN_NUM_AGENTS:-}" ]    && ARGS+=(--num-agents "$KANBAN_NUM_AGENTS")
[ -n "${KANBAN_POLL_INTERVAL:-}" ] && ARGS+=(--poll-interval "$KANBAN_POLL_INTERVAL")
[ -n "${KANBAN_PROFILES_DIR:-}" ]  && ARGS+=(--profiles-dir "$KANBAN_PROFILES_DIR")
[ "${KANBAN_DRY_RUN:-0}" = "1" ]   && ARGS+=(--dry-run)

exec python -m agents.kanban.orchestrator.local "${ARGS[@]+"${ARGS[@]}"}"
