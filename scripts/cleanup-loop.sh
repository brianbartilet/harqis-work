#!/bin/bash
# Periodic cleanup loop: runs cleanup script every 30 seconds
# Usage: bash scripts/cleanup-loop.sh

echo "Starting cleanup loop (runs cleanup every 30 seconds, Ctrl+C to stop)..."

while true; do
    bash "$(dirname "$0")/close-completed-windows.sh" >/dev/null 2>&1
    sleep 30
done
