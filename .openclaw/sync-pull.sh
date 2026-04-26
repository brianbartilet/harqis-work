#!/bin/bash
# OpenClaw Sync - Auto Pull Script (macOS/Linux)
# Pull latest changes from harqis-openclaw-sync
# Run every 30 minutes via cron

set -e

REPO_PATH="${1:-$HOME/GIT/harqis-openclaw-sync}"

echo "=== OpenClaw Sync: Pull Changes ==="
echo "Repository: $REPO_PATH"
echo "Time: $(date '+%Y-%m-%d %H:%M:%S')"
echo ""

# Check if repo exists
if [[ ! -d "$REPO_PATH" ]]; then
    echo "Error: Repository not found at $REPO_PATH"
    exit 1
fi

# Change to repo directory
cd "$REPO_PATH"

# Fetch first to check for changes
echo "Fetching from origin..."
git fetch origin main

# Check if local is behind
LOCAL=$(git rev-parse HEAD)
REMOTE=$(git rev-parse origin/main)

if [[ "$LOCAL" == "$REMOTE" ]]; then
    echo "✓ Already up to date"
    exit 0
fi

# Pull changes
echo "Pulling latest changes..."
git pull origin main

echo ""
echo "✓ Pull complete!"
echo "Latest changes from harqis-openclaw-sync applied"
