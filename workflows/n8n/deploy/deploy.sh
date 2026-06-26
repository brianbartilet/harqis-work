#!/usr/bin/env bash
set -euo pipefail

echo "[INFO] n8n deploy starting..."

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../../.." && pwd)"
COMPOSE_FILE="$REPO_ROOT/docker-compose.yml"
OLD_DATA_DIR="$(cd "$SCRIPT_DIR/../backups/n8n" 2>/dev/null && pwd || true)"

if [[ -n "${HARQIS_DATA_ROOT:-}" ]]; then
  case "$HARQIS_DATA_ROOT" in
    /*) DATA_ROOT="$HARQIS_DATA_ROOT" ;;
    *) DATA_ROOT="$REPO_ROOT/$HARQIS_DATA_ROOT" ;;
  esac
else
  DATA_ROOT="$REPO_ROOT/.harqis-data"
fi
N8N_DATA_DIR="$DATA_ROOT/n8n"

# ---------- sanity checks ----------
if [[ ! -f "$COMPOSE_FILE" ]]; then
  echo "[ERROR] docker-compose.yml not found at: $COMPOSE_FILE"
  exit 1
fi

if ! command -v docker >/dev/null 2>&1; then
  echo "[ERROR] docker is not installed or not in PATH."
  exit 1
fi

# pick docker compose command
if docker compose version >/dev/null 2>&1; then
  DC="docker compose"
elif command -v docker-compose >/dev/null 2>&1; then
  DC="docker-compose"
else
  echo "[ERROR] Neither 'docker compose' nor 'docker-compose' is available."
  exit 1
fi

# ---------- ensure bind-mounted data directory exists ----------
echo "[INFO] Ensuring n8n data directory exists: $N8N_DATA_DIR"
mkdir -p "$N8N_DATA_DIR"

# ---------- one-time migration from old bind folder (if it exists) ----------
if [[ -n "$OLD_DATA_DIR" && -d "$OLD_DATA_DIR" ]]; then
  echo "[INFO] Found existing directory with previous data: $OLD_DATA_DIR"
  echo "[INFO] Copying its contents into n8n data directory '$N8N_DATA_DIR' (safe even if already copied)..."

  docker run --rm \
    -v "$N8N_DATA_DIR:/data" \
    -v "$OLD_DATA_DIR:/source:ro" \
    alpine sh -c "cd /source && cp -a . /data"

  echo "[INFO] Migration copy finished."
else
  echo "[INFO] No previous bind-mounted data directory found to migrate."
fi

# ---------- start n8n ----------
echo "[INFO] Starting n8n via docker compose..."
$DC -f "$COMPOSE_FILE" up -d n8n

echo "[OK] n8n deploy complete. Container should be running now."
