#!/usr/bin/env bash
# flower.sh — Start the Celery Flower monitoring UI.
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/set_env_workflows.sh"

cd "$ROOT_DIRECTORY"

if [ -z "$FLOWER_USER" ]; then
    echo "ERROR: FLOWER_USER environment variable is not set."
    exit 1
fi

if [ -z "$FLOWER_PASS" ]; then
    echo "ERROR: FLOWER_PASS environment variable is not set."
    exit 1
fi

python -m celery -A core.apps.sprout.app.celery:SPROUT flower \
    --port=5555 \
    --address=127.0.0.1 \
    --basic-auth="${FLOWER_USER}:${FLOWER_PASS}"
