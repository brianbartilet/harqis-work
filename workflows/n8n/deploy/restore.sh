#!/usr/bin/env bash
set -euo pipefail

echo "[INFO] n8n restore starting..."

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../../.." && pwd)"
COMPOSE_FILE="$REPO_ROOT/docker-compose.yml"
BACKUP_DIR="$SCRIPT_DIR/../backups"

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

# ---------- restore into bind-mounted data directory ----------
echo "[INFO] Recreating n8n data directory '$N8N_DATA_DIR'..."
rm -rf "$N8N_DATA_DIR"
mkdir -p "$N8N_DATA_DIR"

echo "[INFO] Restoring backup into n8n data directory '$N8N_DATA_DIR'..."
docker run --rm \
  -v "$N8N_DATA_DIR:/data" \
  -v "$BACKUP_FILE:/backup.tgz:ro" \
  alpine sh -c "cd /data && tar xzf /backup.tgz"

echo "[INFO] Restore into data directory complete."

# ---------- repair sqlite + fix permissions ----------
# Fixes duplicate-index schema corruption that can occur after unclean shutdowns.
# Also ensures correct ownership (uid 1000 = node) and removes stale WAL/journal
# files that would cause n8n to report a prior crash on startup.
echo "[INFO] Checking SQLite integrity and fixing permissions..."
docker run --rm \
  -v "$N8N_DATA_DIR:/data" \
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
