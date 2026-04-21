#!/usr/bin/env bash
# deploy.sh — Start the full OpenClaw server stack.
#
# Usage:
#   ./scripts/macos/deploy.sh [OPTIONS]
#
# Options:
#   --workers        Also start Celery workers (Beat + default + adhoc + tcg)
#   --with-core      Include the harqis-core compose file (adds Prism mock server)
#   --down           Stop all services instead of starting them
#   --restart        Stop then start all services
#   -h, --help       Show this help message

set -euo pipefail

# ── Resolve paths ─────────────────────────────────────────────────────────────

REPO_ROOT="$(git -C "$(dirname "$0")" rev-parse --show-toplevel)"
VENV="$REPO_ROOT/.venv"
PYTHON="$VENV/bin/python"

# ── Parse flags ───────────────────────────────────────────────────────────────

START_WORKERS=false
WITH_CORE=false
MODE=up

for arg in "$@"; do
  case $arg in
    --workers)   START_WORKERS=true ;;
    --with-core) WITH_CORE=true ;;
    --down)      MODE=down ;;
    --restart)   MODE=restart ;;
    -h|--help)
      sed -n '2,15p' "$0" | sed 's/^# \?//'
      exit 0
      ;;
    *)
      echo "Unknown option: $arg" >&2
      exit 1
      ;;
  esac
done

# ── Load secrets ──────────────────────────────────────────────────────────────

# Prefer macOS Keychain; fall back to .env/apps.env
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
  set -a
  # shellcheck disable=SC1090
  source "$REPO_ROOT/.env/apps.env"
  set +a
else
  echo "WARNING: No secrets source found (Keychain or .env/apps.env)."
fi

# ── Build compose file list ───────────────────────────────────────────────────

COMPOSE_FILES=(-f "$REPO_ROOT/docker-compose.yml")

if [ "$WITH_CORE" = true ]; then
  # Locate harqis-core's compose file inside the venv site-packages
  CORE_COMPOSE=$("$PYTHON" -c \
    "import core, os; print(os.path.join(os.path.dirname(core.__file__), 'demo', 'docker-compose.yaml'))" \
    2>/dev/null || true)

  if [ -f "$CORE_COMPOSE" ]; then
    echo "Including harqis-core compose: $CORE_COMPOSE"
    COMPOSE_FILES+=(-f "$CORE_COMPOSE")
  else
    echo "WARNING: --with-core specified but harqis-core compose not found (is the venv active?)"
  fi
fi

# ── Docker Compose ────────────────────────────────────────────────────────────

cd "$REPO_ROOT"

case $MODE in
  up)
    echo "Starting services..."
    docker compose "${COMPOSE_FILES[@]}" up -d
    ;;
  down)
    echo "Stopping services..."
    docker compose "${COMPOSE_FILES[@]}" down
    ;;
  restart)
    echo "Restarting services..."
    docker compose "${COMPOSE_FILES[@]}" down
    docker compose "${COMPOSE_FILES[@]}" up -d
    ;;
esac

# ── Celery workers (optional) ─────────────────────────────────────────────────

if [ "$START_WORKERS" = true ] && [ "$MODE" != "down" ]; then
  echo "Activating venv..."
  # shellcheck disable=SC1090
  source "$VENV/bin/activate"
  source "$REPO_ROOT/scripts/linux/set_env_workflows.sh"

  echo "Starting Celery Beat..."
  python "$REPO_ROOT/run_workflows.py" beat &

  echo "Starting Celery workers..."
  WORKFLOW_QUEUE=default python "$REPO_ROOT/run_workflows.py" worker &
  WORKFLOW_QUEUE=adhoc   python "$REPO_ROOT/run_workflows.py" worker &
  WORKFLOW_QUEUE=tcg     python "$REPO_ROOT/run_workflows.py" worker &

  echo "Workers started (Beat + default + adhoc + tcg). Use 'pkill -f run_workflows.py' to stop."
fi

# ── Summary ───────────────────────────────────────────────────────────────────

if [ "$MODE" != "down" ]; then
  echo ""
  echo "Services running:"
  docker compose "${COMPOSE_FILES[@]}" ps --format "table {{.Name}}\t{{.Status}}\t{{.Ports}}"
fi
