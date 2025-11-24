#!/usr/bin/env bash
set -euo pipefail

echo "[INFO] n8n deploy starting..."

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
COMPOSE_FILE="$SCRIPT_DIR/docker-compose.yml"
OLD_DATA_DIR="$(cd "$SCRIPT_DIR/../backups/n8n" 2>/dev/null && pwd || true)"
VOLUME_NAME="deploy_n8n_data"

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

# ---------- ensure volume exists ----------
if ! docker volume inspect "$VOLUME_NAME" >/dev/null 2>&1; then
  echo "[INFO] Creating Docker volume '$VOLUME_NAME'..."
  docker volume create "$VOLUME_NAME" >/dev/null
else
  echo "[INFO] Docker volume '$VOLUME_NAME' already exists."
fi

# ---------- one-time migration from old bind folder (if it exists) ----------
if [[ -n "$OLD_DATA_DIR" && -d "$OLD_DATA_DIR" ]]; then
  echo "[INFO] Found existing directory with previous data: $OLD_DATA_DIR"
  echo "[INFO] Copying its contents into volume '$VOLUME_NAME' (safe even if already copied)..."

  docker run --rm \
    -v "$VOLUME_NAME:/data" \
    -v "$OLD_DATA_DIR:/source" \
    alpine sh -c "cd /source && cp -a . /data"

  echo "[INFO] Migration copy finished."
else
  echo "[INFO] No previous bind-mounted data directory found to migrate."
fi

# ---------- start n8n ----------
echo "[INFO] Starting n8n via docker compose..."
$DC -f "$COMPOSE_FILE" up -d

echo "[OK] n8n deploy complete. Container should be running now."
