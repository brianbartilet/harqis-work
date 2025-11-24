#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BACKUP_DIR="$SCRIPT_DIR/../backups"
VOLUME_NAME="deploy_n8n_data"

mkdir -p "$BACKUP_DIR"

if ! command -v docker >/dev/null 2>&1; then
  echo "[ERROR] docker is not installed or not in PATH."
  exit 1
fi

if ! docker volume inspect "$VOLUME_NAME" >/dev/null 2>&1; then
  echo "[ERROR] Docker volume '$VOLUME_NAME' does not exist."
  exit 1
fi

BACKUP_NAME="backup-$(date +%Y%m%d-%H%M%S).tgz"
BACKUP_PATH="$BACKUP_DIR/$BACKUP_NAME"

echo "[INFO] Creating backup of volume '$VOLUME_NAME' → $BACKUP_PATH"

docker run --rm \
  -v "$VOLUME_NAME:/data" \
  -v "$BACKUP_DIR:/backup" \
  alpine sh -c "cd /data && tar czf /backup/$BACKUP_NAME ."

echo "[OK] Backup created: $BACKUP_PATH"
