#!/bin/bash
# Install or uninstall the cleanup-windows launchd job

set -e

PLIST_SRC="$(dirname "$0")/launchd/ai.openclaw.cleanup-windows.plist"
PLIST_DST="$HOME/Library/LaunchAgents/ai.openclaw.cleanup-windows.plist"

if [[ "$1" == "uninstall" ]]; then
    echo "Uninstalling cleanup job..."
    launchctl unload "$PLIST_DST" 2>/dev/null || true
    rm -f "$PLIST_DST"
    echo "Uninstalled."
    exit 0
fi

# Default: install
echo "Installing cleanup job..."
mkdir -p "$HOME/Library/LaunchAgents"
cp "$PLIST_SRC" "$PLIST_DST"
launchctl load "$PLIST_DST"
echo "Installed and started. View logs: tail -f logs/cleanup-windows.log"
echo "Uninstall with: bash scripts/agents/install-cleanup-job.sh uninstall"
