#!/usr/bin/env bash
# deploy.sh — Bring up (or tear down) the harqis-work platform on this machine.
#
# Roles:
#   host   — the always-on hub: Docker stack + Beat scheduler + worker(s) + frontend
#            + MCP daemon + Kanban orchestrator (acts as 1 agent worker).
#   node   — a remote worker that connects to the host's broker. Runs Celery
#            worker(s) only (no Docker, no scheduler, no frontend).
#
# Usage:
#   ./scripts/sh/deploy.sh --role host [-q default,adhoc] [--no-frontend] [--no-mcp] [--no-kanban]
#   ./scripts/sh/deploy.sh --role node -q hud,tcg,default
#   ./scripts/sh/deploy.sh --role host --down
#
# Backward-compat: if --role is omitted, defaults to "host" (legacy behaviour).
#
# Options:
#   --role host|node   Deployment role (default: host)
#   -q, --queues LIST  Comma-separated Celery queue list for the worker.
#                      Defaults: host=default, node=default. Required-ish on node
#                      if you want to handle anything other than "default".
#                      Examples: "hud,tcg,default" or "code,write".
#   --down             Stop services for this role instead of starting them
#   --docker-only      Only manage Docker (skip LaunchAgent service plists)
#   --no-frontend      Don't start the FastAPI dashboard (host only)
#   --no-mcp           Don't start the MCP daemon (host only)
#   --no-kanban        Don't start the Kanban orchestrator (host only)
#   --no-flower        Don't start the Flower Celery monitor (host only)
#   -h|--help          Show this help message

set -euo pipefail

# ── Resolve paths ─────────────────────────────────────────────────────────────

REPO_ROOT="$(git -C "$(dirname "$0")" rev-parse --show-toplevel)"

# LaunchAgent plists (macOS host). Each plist label maps to the script it runs.
PLIST_SCHEDULER="$HOME/Library/LaunchAgents/work.harqis.scheduler.plist"
PLIST_WORKER="$HOME/Library/LaunchAgents/work.harqis.worker.plist"
PLIST_FRONTEND="$HOME/Library/LaunchAgents/work.harqis.frontend.plist"
PLIST_MCP="$HOME/Library/LaunchAgents/work.harqis.mcp.plist"
PLIST_KANBAN="$HOME/Library/LaunchAgents/work.harqis.kanban.plist"
PLIST_FLOWER="$HOME/Library/LaunchAgents/work.harqis.flower.plist"

# ── Parse flags ───────────────────────────────────────────────────────────────

ROLE=host
MODE=up
DOCKER_ONLY=false
WITH_FRONTEND=true
WITH_MCP=true
WITH_KANBAN=true
WITH_FLOWER=true
QUEUES=""

while [ $# -gt 0 ]; do
  case "$1" in
    --role)         ROLE="$2"; shift 2 ;;
    --role=*)       ROLE="${1#*=}"; shift ;;
    -q|--queues)    QUEUES="$2"; shift 2 ;;
    --queues=*)     QUEUES="${1#*=}"; shift ;;
    --down)         MODE=down; shift ;;
    --docker-only)  DOCKER_ONLY=true; shift ;;
    --no-frontend)  WITH_FRONTEND=false; shift ;;
    --no-mcp)       WITH_MCP=false; shift ;;
    --no-kanban)    WITH_KANBAN=false; shift ;;
    --no-flower)    WITH_FLOWER=false; shift ;;
    -h|--help)
      sed -n '2,29p' "$0" | sed -e 's/^# //' -e 's/^#$//'
      exit 0
      ;;
    *)
      echo "Unknown option: $1" >&2
      exit 1
      ;;
  esac
done

case "$ROLE" in
  host|node) ;;
  *) echo "Invalid --role: $ROLE (expected: host or node)" >&2; exit 1 ;;
esac

# Default queue list per role (when -q not passed)
if [ -z "$QUEUES" ]; then
  QUEUES="default"
fi
# Reject whitespace; trim accidentally-quoted spaces around commas.
QUEUES="$(echo "$QUEUES" | tr -d '[:space:]')"
export WORKFLOW_QUEUE="$QUEUES"

# ── Build the per-role plist list ─────────────────────────────────────────────

PLISTS=()
if [ "$ROLE" = "host" ]; then
  PLISTS+=("$PLIST_SCHEDULER" "$PLIST_WORKER")
  [ "$WITH_FRONTEND" = true ] && PLISTS+=("$PLIST_FRONTEND")
  [ "$WITH_MCP" = true ]      && PLISTS+=("$PLIST_MCP")
  [ "$WITH_KANBAN" = true ]   && PLISTS+=("$PLIST_KANBAN")
  [ "$WITH_FLOWER" = true ]   && PLISTS+=("$PLIST_FLOWER")
else
  # Node: worker only
  PLISTS+=("$PLIST_WORKER")
fi

# ── Load secrets (for docker compose env vars) ────────────────────────────────

_kcget() { security find-generic-password -a harqis -s "$1" -w 2>/dev/null || true; }

if [ "$(uname)" = "Darwin" ] && [ -n "$(_kcget ANTHROPIC_API_KEY)" ]; then
  echo "Loading secrets from macOS Keychain..."
  export ANTHROPIC_API_KEY="$(_kcget ANTHROPIC_API_KEY)"
  export OPENAI_API_KEY="$(_kcget OPENAI_API_KEY)"
  export HARQIS_FERNET_KEY="$(_kcget HARQIS_FERNET_KEY)"
  export CLOUDFLARE_TUNNEL_TOKEN="$(_kcget CLOUDFLARE_TUNNEL_TOKEN)"
elif [ -f "$REPO_ROOT/.env/apps.env" ]; then
  echo "Loading secrets from .env/apps.env..."
  while IFS= read -r line || [ -n "$line" ]; do
    [[ -z "$line" || "$line" == \#* || "$line" != *=* ]] && continue
    key="${line%%=*}"
    value="${line#*=}"
    value="${value%\"}" ; value="${value#\"}"
    value="${value%\'}" ; value="${value#\'}"
    export "$key=$value"
  done < "$REPO_ROOT/.env/apps.env"
else
  echo "WARNING: No secrets source found (Keychain or .env/apps.env)."
fi

# ── Docker Compose (host only) ────────────────────────────────────────────────

cd "$REPO_ROOT"

case $MODE in
  up)
    if [ "$ROLE" = "host" ]; then
      echo "[host] Starting Docker services..."
      docker compose -f "$REPO_ROOT/docker-compose.yml" up -d
      echo ""
      docker compose -f "$REPO_ROOT/docker-compose.yml" ps --format "table {{.Name}}\t{{.Status}}\t{{.Ports}}"
    else
      echo "[node] Skipping Docker — broker is on the host."
    fi

    if [ "$DOCKER_ONLY" = false ]; then
      echo ""
      for plist in "${PLISTS[@]}"; do
        if [ ! -f "$plist" ]; then
          echo "  Skipped (no plist): $(basename "$plist" .plist)"
          continue
        fi
        label=$(basename "$plist" .plist)
        launchctl unload "$plist" 2>/dev/null || true
        launchctl load   "$plist"
        echo "  Started: $label"
      done
    fi

    echo ""
    if [ "$ROLE" = "host" ]; then
      echo "[host] Deploy complete."
      echo "  Components: docker, scheduler, worker(queues=$WORKFLOW_QUEUE)$([ "$WITH_FRONTEND" = true ] && echo ', frontend')$([ "$WITH_MCP" = true ] && echo ', mcp')$([ "$WITH_KANBAN" = true ] && echo ', kanban')$([ "$WITH_FLOWER" = true ] && echo ', flower')"
      echo "  Frontend:   http://localhost:8000"
      [ "$WITH_FLOWER" = true ] && echo "  Flower:     http://localhost:5555  (basic-auth: \$FLOWER_USER:\$FLOWER_PASSWORD)"
      echo "  Logs:       ~/Library/Logs/harqis-*.log"
    else
      echo "[node] Worker attached to broker ${CELERY_BROKER_URL:-(unset — set CELERY_BROKER_URL!)}"
      echo "  Queues:   $WORKFLOW_QUEUE"
    fi
    echo "Stop with: $0 --role $ROLE --down"
    ;;
  down)
    if [ "$DOCKER_ONLY" = false ]; then
      echo "Stopping Python services for role=$ROLE..."
      for plist in "${PLISTS[@]}"; do
        [ -f "$plist" ] && launchctl unload "$plist" 2>/dev/null || true
      done
    fi

    if [ "$ROLE" = "host" ]; then
      echo "Stopping Docker services..."
      docker compose -f "$REPO_ROOT/docker-compose.yml" down
    fi
    echo "All services stopped for role=$ROLE."
    ;;
esac
