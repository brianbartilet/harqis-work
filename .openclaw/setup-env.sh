#!/bin/bash
# OpenClaw Environment Setup Script (Unix/Linux/macOS)
# This script configures OPENCLAW_CONFIG_PATH and OPENCLAW_STATE_DIR

set -e

# Defaults
SYNC_REPO="${1:-./.openclaw/workspace}"
PROFILE="${PROFILE:-default}"
PERMANENT="${PERMANENT:-}"

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
NC='\033[0m' # No Color

# Functions
show_help() {
    cat << 'EOF'
Usage: ./setup-env.sh [options]

Options:
  --sync-repo <path>    Path to the sync repository (default: ./.openclaw/workspace)
  --profile <name>      OpenClaw profile name (default: default)
  --permanent           Save to shell profile (~/.bashrc, ~/.zshrc)
  --help, -h            Display this help message

Environment Variables:
  SYNC_REPO             Override sync repository path
  PROFILE               Override profile name
  PERMANENT             Set to 1 to enable permanent setup

Examples:
  # Set environment variables for current session
  ./setup-env.sh

  # Use a custom sync repo path
  ./setup-env.sh /mnt/shared/openclaw

  # Permanently set (prompts for shell profile)
  PERMANENT=1 ./setup-env.sh

Description:
  This script configures OpenClaw to use a specific directory for storing
  configuration and state. This allows you to sync your OpenClaw setup
  across machines.

  Environment Variables Set:
  - OPENCLAW_CONFIG_PATH: Where OpenClaw reads/writes configuration
  - OPENCLAW_STATE_DIR: Where OpenClaw stores session and runtime state
EOF
}

# Parse arguments
while [[ $# -gt 0 ]]; do
    case $1 in
        --help|-h)
            show_help
            exit 0
            ;;
        --sync-repo)
            SYNC_REPO="$2"
            shift 2
            ;;
        --profile)
            PROFILE="$2"
            shift 2
            ;;
        --permanent)
            PERMANENT=1
            shift
            ;;
        *)
            echo "Unknown option: $1"
            show_help
            exit 1
            ;;
    esac
done

# Validate sync repo exists
if [[ ! -d "$SYNC_REPO" ]]; then
    echo -e "${RED}Error: Sync repository path not found: $SYNC_REPO${NC}"
    exit 1
fi

# Create directories
CONFIG_PATH="$SYNC_REPO/config"
STATE_PATH="$SYNC_REPO/state"

if [[ ! -d "$CONFIG_PATH" ]]; then
    mkdir -p "$CONFIG_PATH"
    echo -e "${GREEN}Created: $CONFIG_PATH${NC}"
fi

if [[ ! -d "$STATE_PATH" ]]; then
    mkdir -p "$STATE_PATH"
    echo -e "${GREEN}Created: $STATE_PATH${NC}"
fi

# Export environment variables for current session
export OPENCLAW_CONFIG_PATH="$CONFIG_PATH"
export OPENCLAW_STATE_DIR="$STATE_PATH"

if [[ "$PROFILE" != "default" ]]; then
    export OPENCLAW_PROFILE="$PROFILE"
fi

echo ""
echo -e "${CYAN}Environment variables set for current session:${NC}"
echo "  OPENCLAW_CONFIG_PATH=$CONFIG_PATH"
echo "  OPENCLAW_STATE_DIR=$STATE_PATH"
if [[ "$PROFILE" != "default" ]]; then
    echo "  OPENCLAW_PROFILE=$PROFILE"
fi

# Optionally save permanently
if [[ "$PERMANENT" == "1" ]]; then
    # Detect shell profile
    if [[ -f "$HOME/.zshrc" ]]; then
        SHELL_PROFILE="$HOME/.zshrc"
        SHELL_TYPE="zsh"
    elif [[ -f "$HOME/.bashrc" ]]; then
        SHELL_PROFILE="$HOME/.bashrc"
        SHELL_TYPE="bash"
    elif [[ -f "$HOME/.bash_profile" ]]; then
        SHELL_PROFILE="$HOME/.bash_profile"
        SHELL_TYPE="bash"
    else
        echo -e "${YELLOW}Warning: Could not detect shell profile${NC}"
        echo "Please manually add these lines to your shell profile:"
        echo "  export OPENCLAW_CONFIG_PATH='$CONFIG_PATH'"
        echo "  export OPENCLAW_STATE_DIR='$STATE_PATH'"
        if [[ "$PROFILE" != "default" ]]; then
            echo "  export OPENCLAW_PROFILE='$PROFILE'"
        fi
        exit 0
    fi

    # Check if already configured
    if grep -q "OPENCLAW_CONFIG_PATH" "$SHELL_PROFILE"; then
        echo -e "${YELLOW}OpenClaw environment already configured in $SHELL_PROFILE${NC}"
        echo "Remove the old configuration manually if you want to update it"
    else
        # Add to shell profile
        cat >> "$SHELL_PROFILE" << EOL

# OpenClaw environment configuration
export OPENCLAW_CONFIG_PATH='$CONFIG_PATH'
export OPENCLAW_STATE_DIR='$STATE_PATH'
EOL
        
        if [[ "$PROFILE" != "default" ]]; then
            echo "export OPENCLAW_PROFILE='$PROFILE'" >> "$SHELL_PROFILE"
        fi

        echo -e "${GREEN}Environment variables saved to $SHELL_PROFILE${NC}"
        echo -e "${YELLOW}Note: Run 'source $SHELL_PROFILE' or restart your terminal${NC}"
    fi
else
    echo ""
    echo -e "${CYAN}To make this permanent, run:${NC}"
    echo "  PERMANENT=1 ./setup-env.sh"
    echo ""
    echo "Or export the variables in your shell profile (~/.bashrc or ~/.zshrc)"
fi

echo ""
echo -e "${GREEN}Setup complete!${NC}"
echo -e "${CYAN}OpenClaw will now use this sync repo for configuration and state persistence${NC}"
