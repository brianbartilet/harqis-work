#!/bin/bash
# Install or uninstall the cleanup-windows launchd job

set -e

PLIST_SRC="$(dirname "$0")/launchd/ai.hermes.cleanup-windows.plist"
PLIST_DST="$HOME/Library/LaunchAgents/ai.hermes.cleanup-windows.plist"
LEGACY_DST="$HOME/Library/LaunchAgents/ai.openclaw.cleanup-windows.plist"  # pre-Hermes

if [[ "$1" == "uninstall" ]]; then
    echo "Uninstalling cleanup job..."
    launchctl unload "$PLIST_DST" 2>/dev/null || true
    rm -f "$PLIST_DST"
    # Best-effort removal of the deprecated OpenClaw-era job, if still installed.
    launchctl unload "$LEGACY_DST" 2>/dev/null || true
    rm -f "$LEGACY_DST"
    echo "Uninstalled."
    exit 0
fi

# Migration: drop the deprecated OpenClaw-era job before installing the Hermes one.
launchctl unload "$LEGACY_DST" 2>/dev/null || true
rm -f "$LEGACY_DST"

# Default: install
echo "Installing cleanup job..."
mkdir -p "$HOME/Library/LaunchAgents"
cp "$PLIST_SRC" "$PLIST_DST"
launchctl load "$PLIST_DST"
echo "Installed and started. View logs: tail -f logs/cleanup-windows.log"
echo "Uninstall with: bash scripts/agents/install-cleanup-job.sh uninstall"
