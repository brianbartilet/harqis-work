#!/usr/bin/env bash
set -euo pipefail

echo "[INFO] n8n restore starting..."

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
COMPOSE_FILE="$SCRIPT_DIR/../../../docker-compose.yml"
BACKUP_DIR="$SCRIPT_DIR/../backups"
VOLUME_NAME="harqis-work_n8n_data"

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
  if [[ "$1" == *.tgz ]]; then
    BACKUP_FILE="$BACKUP_DIR/$1"
  else
    BACKUP_FILE="$BACKUP_DIR/$1.tgz"
  fi
else
  BACKUP_FILE="$(ls -1t "$BACKUP_DIR"/backup-*.tgz 2>/dev/null | head -n 1 || true)"
fi

if [[ -z "${BACKUP_FILE:-}" || ! -f "$BACKUP_FILE" ]]; then
  echo "[ERROR] Backup file not found."
  echo "        Looked for: ${BACKUP_FILE:-<none>}"
  echo "        Or there are no files matching: $BACKUP_DIR/backup-*.tgz"
  exit 1
fi

echo "[INFO] Using backup file: $BACKUP_FILE"

# ---------- stop n8n container ----------
echo "[INFO] Stopping n8n container..."
$DC -f "$COMPOSE_FILE" stop n8n

# ---------- recreate volume ----------
echo "[INFO] Recreating Docker volume '$VOLUME_NAME'..."
docker volume rm -f "$VOLUME_NAME" >/dev/null 2>&1 || true
docker volume create "$VOLUME_NAME" >/dev/null

# ---------- restore into volume ----------
echo "[INFO] Restoring backup into volume '$VOLUME_NAME'..."
docker run --rm \
  -v "$VOLUME_NAME:/data" \
  -v "$BACKUP_FILE:/backup.tgz:ro" \
  alpine sh -c "cd /data && tar xzf /backup.tgz"

echo "[INFO] Restore into volume complete."

# ---------- repair sqlite + fix permissions ----------
# Fixes duplicate-index schema corruption that can occur after unclean shutdowns.
# Also ensures correct ownership (uid 1000 = node) and removes stale WAL/journal
# files that would cause n8n to report a prior crash on startup.
echo "[INFO] Checking SQLite integrity and fixing permissions..."
docker run --rm \
  -v "$VOLUME_NAME:/data" \
  alpine sh -c '
    apk add --no-cache sqlite >/dev/null 2>&1

    DB=/data/database.sqlite

    # Fix ownership and permissions so the node user (uid 1000) can read/write
    chown 1000:1000 "$DB" 2>/dev/null || true
    chmod 0600 "$DB"

    # Remove stale WAL and crash journal left by previous failed sessions
    rm -f /data/database.sqlite-shm /data/database.sqlite-wal /data/crash.journal

    # Test if the schema is intact by querying a core table
    if ! sqlite3 "$DB" "SELECT COUNT(*) FROM workflow_entity;" >/dev/null 2>&1; then
      echo "[INFO] Schema corruption detected — repairing via dump/reimport..."
      sqlite3 "$DB" .dump > /tmp/db_dump.sql
      mv "$DB" "${DB}.corrupt_bak"
      sqlite3 "$DB" < /tmp/db_dump.sql
      chown 1000:1000 "$DB"
      chmod 0600 "$DB"
      echo "[INFO] Schema repair complete. Corrupt original kept as ${DB}.corrupt_bak"
    else
      echo "[INFO] SQLite schema OK."
    fi
  '

# ---------- start n8n container again ----------
echo "[INFO] Starting n8n container..."
$DC -f "$COMPOSE_FILE" up -d n8n

echo "[OK] Restore finished. n8n should now be running with restored data."
