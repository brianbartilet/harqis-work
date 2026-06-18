#!/bin/bash
# Clean up local git worktrees
# On gateway: delete worktrees for branches already merged to origin/main
# On local: delete worktrees idle >24 hours
# Usage: cleanup-worktrees.sh [local|gateway] (auto-detects if not specified)

set -e

WORKSPACE_DIR="${WORKSPACE_DIR:-.}"
WORKTREE_DIR="$WORKSPACE_DIR/.claude/worktrees"
IDLE_THRESHOLD_HOURS=24
IS_GATEWAY=false

# Allow explicit mode override
if [[ "$1" == "local" ]]; then
  IS_GATEWAY=false
elif [[ "$1" == "gateway" ]]; then
  IS_GATEWAY=true
else
  # Auto-detect based on hostname
  HOSTNAME=$(hostname)
  if [[ "$HOSTNAME" =~ "mac-mini" ]] || [[ "$HOSTNAME" == "harqis-ones-mac-mini" ]]; then
    IS_GATEWAY=true
  fi
fi

# Exit if no worktrees exist
if [[ ! -d "$WORKTREE_DIR" ]]; then
  echo "No worktree directory found at $WORKTREE_DIR"
  exit 0
fi

DELETED_COUNT=0
SKIPPED_COUNT=0

# Get list of worktrees
while IFS= read -r worktree_path; do
  if [[ -z "$worktree_path" ]]; then
    continue
  fi

  worktree_name=$(basename "$worktree_path")

  # Skip if not a directory
  if [[ ! -d "$worktree_path" ]]; then
    continue
  fi

  # Get the branch name from the worktree
  BRANCH_NAME=""
  if [[ -f "$worktree_path/.git" ]]; then
    # .git is a file in worktrees pointing to the main repo
    BRANCH_NAME=$(cd "$worktree_path" && git symbolic-ref --short HEAD 2>/dev/null || echo "")
  fi

  if [[ -z "$BRANCH_NAME" ]]; then
    SKIPPED_COUNT=$((SKIPPED_COUNT + 1))
    continue
  fi

  SHOULD_DELETE=false
  DELETE_REASON=""

  if $IS_GATEWAY; then
    # On gateway: delete if branch is merged into origin/main
    cd "$WORKSPACE_DIR"
    if git rev-parse --verify "origin/main" &>/dev/null; then
      # Check if branch is an ancestor of origin/main (i.e., merged)
      if git merge-base --is-ancestor "$BRANCH_NAME" "origin/main" 2>/dev/null; then
        SHOULD_DELETE=true
        DELETE_REASON="branch merged into origin/main"
      fi
    fi
  else
    # On local: delete if worktree is idle >24 hours
    MODIFIED_TIME=$(stat -f%m "$worktree_path" 2>/dev/null || stat -c%Y "$worktree_path" 2>/dev/null || echo 0)
    CURRENT_TIME=$(date +%s)
    IDLE_SECONDS=$((CURRENT_TIME - MODIFIED_TIME))
    IDLE_HOURS=$((IDLE_SECONDS / 3600))

    if [[ $IDLE_HOURS -gt $IDLE_THRESHOLD_HOURS ]]; then
      SHOULD_DELETE=true
      DELETE_REASON="idle ${IDLE_HOURS}h (threshold: ${IDLE_THRESHOLD_HOURS}h)"
    fi
  fi

  if $SHOULD_DELETE; then
    # Remove the worktree
    if git worktree remove "$worktree_path" 2>/dev/null || rm -rf "$worktree_path"; then
      echo "✓ Deleted worktree: $worktree_name ($BRANCH_NAME) — $DELETE_REASON"
      DELETED_COUNT=$((DELETED_COUNT + 1))
    else
      echo "✗ Failed to delete worktree: $worktree_name"
    fi
  fi
done < <(find "$WORKTREE_DIR" -mindepth 1 -maxdepth 1 -type d)

# Summary
LOCATION="local"
$IS_GATEWAY && LOCATION="gateway"
echo ""
echo "Worktree cleanup ($LOCATION): $DELETED_COUNT deleted, $SKIPPED_COUNT skipped"
