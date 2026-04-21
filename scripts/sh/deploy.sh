#!/usr/bin/env bash
# deploy.sh — Start Docker services + Celery Beat scheduler + default worker + frontend.
#
# Usage:
#   ./scripts/sh/deploy.sh [--down] [--docker-only]
#
# Options:
#   --down         Stop all services instead of starting them
#   --docker-only  Only manage Docker (skip LaunchAgent service plists)
#   -h|--help      Show this help message

set -euo pipefail

# ── Resolve paths ─────────────────────────────────────────────────────────────

REPO_ROOT="$(git -C "$(dirname "$0")" rev-parse --show-toplevel)"

PLISTS=(
  "$HOME/Library/LaunchAgents/work.harqis.scheduler.plist"
  "$HOME/Library/LaunchAgents/work.harqis.worker.plist"
  "$HOME/Library/LaunchAgents/work.harqis.frontend.plist"
)

# ── Parse flags ───────────────────────────────────────────────────────────────

MODE=up
DOCKER_ONLY=false

for arg in "$@"; do
  case $arg in
    --down)         MODE=down ;;
    --docker-only)  DOCKER_ONLY=true ;;
    -h|--help)
      sed -n '2,11p' "$0" | sed 's/^# \?//'
      exit 0
      ;;
    *)
      echo "Unknown option: $arg" >&2
      exit 1
      ;;
  esac
done

# ── Load secrets (for docker compose env vars) ────────────────────────────────

_kcget() { security find-generic-password -a harqis -s "$1" -w 2>/dev/null || true; }

KEYCHAIN_KEY=$(_kcget ANTHROPIC_API_KEY)
if [ -n "$KEYCHAIN_KEY" ]; then
  echo "Loading secrets from macOS Keychain..."
  export ANTHROPIC_API_KEY="$KEYCHAIN_KEY"
  export OPENAI_API_KEY=$(_kcget OPENAI_API_KEY)
  export HARQIS_FERNET_KEY=$(_kcget HARQIS_FERNET_KEY)
  export CLOUDFLARE_TUNNEL_TOKEN=$(_kcget CLOUDFLARE_TUNNEL_TOKEN)
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

# ── Docker Compose ────────────────────────────────────────────────────────────

cd "$REPO_ROOT"

case $MODE in
  up)
    echo "Starting Docker services..."
    docker compose -f "$REPO_ROOT/docker-compose.yml" up -d

    echo ""
    docker compose -f "$REPO_ROOT/docker-compose.yml" ps --format "table {{.Name}}\t{{.Status}}\t{{.Ports}}"

    # ── Python services (via LaunchAgent plists) ──────────────────────────────

    if [ "$DOCKER_ONLY" = false ]; then
      echo ""
      for plist in "${PLISTS[@]}"; do
        label=$(basename "$plist" .plist)
        launchctl unload "$plist" 2>/dev/null || true
        launchctl load   "$plist"
        echo "  Started: $label"
      done
    fi

    echo ""
    echo "Deploy complete. Scheduler + default worker + frontend running."
    echo "Logs: ~/Library/Logs/harqis-*.log"
    echo "Stop with: $0 --down"
    ;;
  down)
    if [ "$DOCKER_ONLY" = false ]; then
      echo "Stopping Python services..."
      for plist in "${PLISTS[@]}"; do
        launchctl unload "$plist" 2>/dev/null || true
      done
    fi

    echo "Stopping Docker services..."
    docker compose -f "$REPO_ROOT/docker-compose.yml" down
    echo "All services stopped."
    ;;
esac
