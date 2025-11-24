#!/usr/bin/env bash
set -euo pipefail

echo "[INFO] n8n restore starting..."

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
COMPOSE_FILE="$SCRIPT_DIR/docker-compose.yml"
BACKUP_DIR="$SCRIPT_DIR/../backups"
VOLUME_NAME="deploy_n8n_data"

# ---------- sanity checks ----------
if [[ ! -f "$COMPOSE_FILE" ]]; then
  echo "[ERROR] docker-compose.yml not found at: $COMPOSE_FILE"
  exit 1
fi

if [[ ! -d "$BACKUP_DIR" ]]; then
  echo "[ERROR] Backup directory not found: $BACKUP_DIR"
  exit 1
fi

if ! command -v docker >/dev/null 2>&1; then
  echo "[ERROR] docker is not installed or not in PATH."
  exit 1
fi

# Pick docker compose command
if docker compose version >/dev/null 2>&1; then
  DC="docker compose"
elif command -v docker-compose >/dev/null 2>&1; then
  DC="docker-compose"
else
  echo "[ERROR] Neither 'docker compose' nor 'docker-compose' is available."
  exit 1
fi

# ---------- choose backup file ----------
if [[ $# -ge 1 ]]; then
  # If user gave bare name (without .tgz), append it
  if [[ "$1" == *.tgz ]]; then
    BACKUP_FILE="$BACKUP_DIR/$1"
  else
    BACKUP_FILE="$BACKUP_DIR/$1.tgz"
  fi
else
  # Use latest backup-*.tgz
  BACKUP_FILE="$(ls -1t "$BACKUP_DIR"/backup-*.tgz 2>/dev/null | head -n 1 || true)"
fi

if [[ -z "${BACKUP_FILE:-}" || ! -f "$BACKUP_FILE" ]]; then
  echo "[ERROR] Backup file not found."
  echo "        Looked for: $BACKUP_FILE"
  echo "        Or there are no files matching: $BACKUP_DIR/backup-*.tgz"
  exit 1
fi

echo "[INFO] Using backup file: $BACKUP_FILE"

# ---------- stop container ----------
echo "[INFO] Stopping n8n container..."
$DC -f "$COMPOSE_FILE" down

# ---------- recreate volume ----------
echo "[INFO] Recreating Docker volume '$VOLUME_NAME'..."
docker volume rm -f "$VOLUME_NAME" >/dev/null 2>&1 || true
docker volume create "$VOLUME_NAME" >/dev/null

# ---------- restore into volume ----------
echo "[INFO] Restoring backup into volume '$VOLUME_NAME'..."
docker run --rm \
  -v "$VOLUME_NAME:/data" \
  -v "$BACKUP_FILE:/backup.tgz" \
  alpine sh -c "cd /data && tar xzf /backup.tgz"

echo "[INFO] Restore into volume complete."

# ---------- start container again ----------
echo "[INFO] Starting n8n container..."
$DC -f "$COMPOSE_FILE" up -d

echo "[OK] Restore finished. n8n should now be running with restored data."
