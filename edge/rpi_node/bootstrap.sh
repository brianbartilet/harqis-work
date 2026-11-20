#!/usr/bin/env bash
#
# edge/rpi_node/bootstrap.sh
#
# First-time bootstrap for a Raspberry Pi (Raspberry Pi OS 64-bit / any ARM
# Linux) to join the harqis-work cluster as a Celery worker node over Tailscale.
#
# It mirrors the cloud-init bootstrap in docs/info/VPS-CLUSTER-AGENT-DESIGN.md §9,
# with `tailscale up` replacing the hand-distributed WireGuard wg0.conf.
#
# The Pi holds NO application secrets: it fetches resolved config at startup over
# the tailnet via the Redis/HTTP backend documented in
# docs/info/WORKER-CONFIG-DISTRIBUTION.md. Only the broker/config endpoint lives
# in .env/worker.env.
#
# Usage:
#   sudo HARQIS_HOST_MAGICDNS=host.<tailnet>.ts.net \
#        HARQIS_QUEUES=default,worker,default_broadcast,hfl_broadcast \
#        bash edge/rpi_node/bootstrap.sh
#
# Re-running is safe: each step is idempotent.

set -euo pipefail

# ── Tunables (override via environment) ──────────────────────────────────────
REPO_URL="${HARQIS_REPO_URL:-https://github.com/brianbartilet/harqis-work.git}"
REPO_DIR="${HARQIS_REPO_DIR:-/opt/harqis-work}"
HOST_MAGICDNS="${HARQIS_HOST_MAGICDNS:-}"          # e.g. host.tailXXXX.ts.net  (REQUIRED)
QUEUES="${HARQIS_QUEUES:-default,worker,default_broadcast,hfl_broadcast}"
CONCURRENCY="${HARQIS_CONCURRENCY:-2}"
CONFIG_SOURCE="${HARQIS_CONFIG_SOURCE:-redis}"      # redis | http  (see WORKER-CONFIG-DISTRIBUTION.md)

log() { printf '\033[1;36m[rpi-bootstrap]\033[0m %s\n' "$*"; }
die() { printf '\033[1;31m[rpi-bootstrap] ERROR:\033[0m %s\n' "$*" >&2; exit 1; }

[ "$(id -u)" -eq 0 ] || die "run with sudo/root"
[ -n "$HOST_MAGICDNS" ] || die "set HARQIS_HOST_MAGICDNS to the host's Tailscale MagicDNS name (or its 100.x IP)"

# ── 1. System packages ───────────────────────────────────────────────────────
log "installing base packages (git, python3, venv)"
export DEBIAN_FRONTEND=noninteractive
apt-get update -qq
apt-get install -y -qq git python3 python3-venv python3-pip curl >/dev/null

# ── 2. Tailscale — install + join the tailnet ────────────────────────────────
if ! command -v tailscale >/dev/null 2>&1; then
  log "installing Tailscale"
  curl -fsSL https://tailscale.com/install.sh | sh
fi
log "joining the tailnet (a browser/OAuth auth URL will be printed if not pre-authed)"
# --ssh: allow tailnet SSH for management (dumps pull-targets / sync-host).
# Tag the node so tailnet ACLs can scope it to the host broker/Redis/ES only.
tailscale up --ssh --hostname "$(hostname -s)" --advertise-tags=tag:edge || \
  tailscale up --ssh --hostname "$(hostname -s)"

# ── 3. Repo ──────────────────────────────────────────────────────────────────
if [ ! -d "$REPO_DIR/.git" ]; then
  log "cloning $REPO_URL -> $REPO_DIR"
  git clone --depth 1 "$REPO_URL" "$REPO_DIR"
else
  log "repo present; pulling latest"
  git -C "$REPO_DIR" pull --ff-only || true
fi

# ── 4. Python venv + deps ────────────────────────────────────────────────────
log "creating venv + installing requirements (this can take a while on a Pi)"
python3 -m venv "$REPO_DIR/.venv"
"$REPO_DIR/.venv/bin/pip" install --upgrade pip >/dev/null
"$REPO_DIR/.venv/bin/pip" install -r "$REPO_DIR/requirements.txt"

# ── 5. Secret-less worker config ─────────────────────────────────────────────
# Points the broker + config store at the host over the tailnet. No API keys
# land here — they are resolved on the host and fetched at startup.
log "writing .env/worker.env (CONFIG_SOURCE=$CONFIG_SOURCE, host=$HOST_MAGICDNS)"
mkdir -p "$REPO_DIR/.env"
case "$CONFIG_SOURCE" in
  redis)
    cat > "$REPO_DIR/.env/worker.env" <<EOF
CONFIG_SOURCE=redis
CELERY_BROKER_URL=amqp://guest:guest@${HOST_MAGICDNS}:5672/
CONFIG_REDIS_URL=redis://${HOST_MAGICDNS}:6379/1
EOF
    ;;
  http)
    [ -n "${HARQIS_CONFIG_SERVER_TOKEN:-}" ] || die "CONFIG_SOURCE=http requires HARQIS_CONFIG_SERVER_TOKEN"
    cat > "$REPO_DIR/.env/worker.env" <<EOF
CONFIG_SOURCE=http
CELERY_BROKER_URL=amqp://guest:guest@${HOST_MAGICDNS}:5672/
CONFIG_SERVER_URL=http://${HOST_MAGICDNS}:8765
CONFIG_SERVER_TOKEN=${HARQIS_CONFIG_SERVER_TOKEN}
EOF
    ;;
  *) die "unknown CONFIG_SOURCE=$CONFIG_SOURCE (use redis or http)";;
esac

# ── 6. Start the worker ──────────────────────────────────────────────────────
# Auto-detection: deploy.py maps this Pi's hostname → the [rpi-node] block in
# machines.toml (via machines.local.toml). Here we launch directly so the
# bootstrap is self-contained; for a managed daemon, add a systemd unit that
# runs the same line.
log "starting Celery worker on queues: $QUEUES (concurrency=$CONCURRENCY)"
cd "$REPO_DIR"
# launch.py reads concurrency/pool from env (see cmd_worker). prefork is fine on
# ARM Linux; override with WORKFLOW_POOL if a task needs gevent/threads.
export WORKFLOW_CONCURRENCY="$CONCURRENCY"
exec "$REPO_DIR/.venv/bin/python" scripts/launch.py worker --queues "$QUEUES"
