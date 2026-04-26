#!/bin/bash
# OpenClaw Sync - Auto Push Script (macOS/Linux)
# Commit and push changes to harqis-openclaw-sync
# Run every 15 minutes via cron

set -e

REPO_PATH="${1:-$HOME/GIT/harqis-openclaw-sync}"
COMMIT_MESSAGE="${2:-sync: auto-commit workspace changes}"

echo "=== OpenClaw Sync: Push Changes ==="
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

# Check for changes
echo "Checking for changes..."
STATUS=$(git status --porcelain)

if [[ -z "$STATUS" ]]; then
    echo "✓ No changes to commit"
    exit 0
fi

# Stage all changes
echo "Staging changes..."
git add -A

# Commit
TIMESTAMP=$(date '+%Y-%m-%d %H:%M:%S')
FULL_MESSAGE="$COMMIT_MESSAGE [$TIMESTAMP]"
echo "Committing: $FULL_MESSAGE"
git commit -m "$FULL_MESSAGE"

# Push
echo "Pushing to origin..."
git push origin main

echo ""
echo "✓ Sync complete!"
echo "Changes pushed to harqis-openclaw-sync"
