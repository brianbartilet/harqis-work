#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../../.." && pwd)"
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

mkdir -p "$BACKUP_DIR"

if ! command -v docker >/dev/null 2>&1; then
  echo "[ERROR] docker is not installed or not in PATH."
  exit 1
fi

if [[ ! -d "$N8N_DATA_DIR" ]]; then
  echo "[ERROR] n8n data directory does not exist: $N8N_DATA_DIR"
  echo "        This should match docker-compose.yml: \\${HARQIS_DATA_ROOT:-./.harqis-data}/n8n:/home/node/.n8n"
  exit 1
fi

if [[ ! -f "$N8N_DATA_DIR/database.sqlite" ]]; then
  echo "[ERROR] n8n database not found: $N8N_DATA_DIR/database.sqlite"
  exit 1
fi

# ---------- verify database health before backing up ----------
echo "[INFO] Verifying SQLite database health in $N8N_DATA_DIR..."
DB_CHECK=$(docker run --rm \
  -v "$N8N_DATA_DIR:/data:ro" \
  alpine sh -c "apk add --no-cache sqlite >/dev/null 2>&1 && sqlite3 /data/database.sqlite 'SELECT COUNT(*) FROM workflow_entity;' 2>&1" || true)

if echo "$DB_CHECK" | grep -qi "error\|corrupt\|malformed"; then
  echo "[ERROR] Database health check failed: $DB_CHECK"
  echo "        Run restore.sh first to repair the database before taking a backup."
  exit 1
fi

echo "[INFO] Database OK (workflow count: $DB_CHECK)"

BACKUP_NAME="backup-$(date +%Y%m%d-%H%M%S).tgz"
BACKUP_PATH="$BACKUP_DIR/$BACKUP_NAME"

echo "[INFO] Creating backup of n8n data directory '$N8N_DATA_DIR' → $BACKUP_PATH"

docker run --rm \
  -v "$N8N_DATA_DIR:/data:ro" \
  -v "$BACKUP_DIR:/backup" \
  alpine sh -c "cd /data && tar czf /backup/$BACKUP_NAME ."

echo "[OK] Backup created: $BACKUP_PATH"
