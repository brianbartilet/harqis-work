# OpenClaw Environment Setup

This directory contains scripts to configure OpenClaw to use this sync repository for storing configuration and state files.

## Overview

By default, OpenClaw stores configuration and state in your user home directory (`~/.openclaw`). This guide shows you how to redirect OpenClaw to use this repository for persistence, allowing you to:

- **Sync across machines** via Git
- **Version control** your OpenClaw configuration
- **Share settings** across multiple profiles
- **Backup and restore** easily

## Quick Start

### Windows (PowerShell)

```powershell
# For current session only
.\setup-env.ps1

# For permanent setup (requires admin)
.\setup-env.ps1 -Permanent
```

### Windows (Command Prompt)

```batch
REM For current session only
setup-env.bat

REM For permanent setup (requires admin)
setup-env.bat --permanent
```

## What Gets Set

The setup script creates and configures two environment variables:

| Variable | Purpose | Location |
|----------|---------|----------|
| `OPENCLAW_CONFIG_PATH` | Configuration files (tokens, channels, etc.) | `./config/` |
| `OPENCLAW_STATE_DIR` | Runtime state (sessions, cache, etc.) | `./state/` |

## Directory Structure

After setup, your `.openclaw` directory will look like:

```
.openclaw/
├── workspace/              # Agent workspace (main session context)
├── config/                 # OpenClaw configuration (synced)
│   ├── openclaw.json       # Main config file
│   ├── channels/           # Channel credentials
│   └── ...
├── state/                  # OpenClaw runtime state (often in .gitignore)
│   ├── sessions/           # Conversation sessions
│   ├── cache/              # Temporary data
│   └── ...
├── setup-env.ps1           # PowerShell setup script
├── setup-env.bat           # Batch setup script
└── SETUP_ENV.md            # This file
```

## Advanced Options

### Custom Sync Path

```powershell
# Use a different directory
.\setup-env.ps1 -SyncRepo "D:\my-openclaw-sync"
```

```batch
setup-env.bat --sync-repo "D:\my-openclaw-sync"
```

### Named Profiles

OpenClaw supports multiple profiles with isolated state:

```powershell
# Create a "work" profile
.\setup-env.ps1 -Profile "work"

# Later, switch profiles with:
openclaw --profile work tui
```

## Git Integration

### Recommended `.gitignore`

Add to your repository's `.gitignore` to track config but exclude sensitive state:

```gitignore
# OpenClaw runtime state (not synced)
.openclaw/state/

# Sensitive files
.openclaw/config/secrets.json
.openclaw/config/tokens/
.env/
```

### Tracking Configuration Only

If you want to version-control your OpenClaw configuration:

```bash
git add .openclaw/config/
git add .openclaw/workspace/
git add .openclaw/setup-env.*
git add .openclaw/SETUP_ENV.md

# Exclude state
git check-ignore .openclaw/state/
```

## Verification

To verify your setup:

```powershell
# Check environment variables
$env:OPENCLAW_CONFIG_PATH
$env:OPENCLAW_STATE_DIR

# Verify directories exist
Test-Path $env:OPENCLAW_CONFIG_PATH
Test-Path $env:OPENCLAW_STATE_DIR

# Start OpenClaw and verify it's using the sync repo
openclaw tui
```

## Troubleshooting

### Environment Variables Not Taking Effect

If you set with `-Permanent` but applications don't see the new variables:

1. **Restart your application** (especially terminal/IDE)
2. **Verify with** `echo %OPENCLAW_CONFIG_PATH%` in a fresh terminal
3. **Check user environment** via Windows Settings → Environment Variables

### Permission Denied on setup-env.ps1

If PowerShell won't execute the script:

```powershell
# Allow scripts for this session
Set-ExecutionPolicy -ExecutionPolicy Bypass -Scope Process

# Then run the setup
.\setup-env.ps1
```

### State Directory Growing Large

The `state/` directory may grow over time with sessions and cache:

```bash
# Clean up old sessions (safe)
rm -rf .openclaw/state/sessions/*

# Or configure OpenClaw to use a separate state directory
# See openclaw config --help
```

## Integration with Development Tools

### VS Code

Add to your workspace `.vscode/settings.json`:

```json
{
  "terminal.integrated.env.windows": {
    "OPENCLAW_CONFIG_PATH": "${workspaceFolder}/.openclaw/config",
    "OPENCLAW_STATE_DIR": "${workspaceFolder}/.openclaw/state"
  }
}
```

### PyCharm / IntelliJ

Configure in the Run Configuration:

1. **Run** → **Edit Configurations**
2. Select your OpenClaw run config
3. Add to **Environment variables**:
   ```
   OPENCLAW_CONFIG_PATH=./.openclaw/config
   OPENCLAW_STATE_DIR=./.openclaw/state
   ```

### Docker / Containers

Mount the `.openclaw` directory:

```bash
docker run -v $(pwd)/.openclaw:/root/.openclaw openclaw:latest openclaw tui
```

## Syncing Across Machines

### Git-Based Sync

1. **First machine:** Run setup and commit:
   ```bash
   .\setup-env.ps1
   git add .openclaw/config/
   git commit -m "Add OpenClaw configuration"
   git push
   ```

2. **Second machine:** Pull and setup:
   ```bash
   git pull
   .\setup-env.ps1
   # Your config is now in sync!
   ```

### Manual Sync

Copy the `.openclaw/config` directory to another machine:

```bash
# Backup
cp -r .openclaw/config ./openclaw-config-backup

# Restore on another machine
cp -r ./openclaw-config-backup .openclaw/config
```

## Resetting to Defaults

To revert to default OpenClaw directories:

```powershell
# Remove environment variables
[Environment]::SetEnvironmentVariable("OPENCLAW_CONFIG_PATH", $null, "User")
[Environment]::SetEnvironmentVariable("OPENCLAW_STATE_DIR", $null, "User")

# Restart your terminal
```

Or use the OpenClaw CLI:

```bash
openclaw reset
```

## Further Reading

- [OpenClaw Configuration](https://docs.openclaw.ai/config)
- [OpenClaw CLI Reference](https://docs.openclaw.ai/cli)
- [Managing Profiles](https://docs.openclaw.ai/cli/config/profiles)

---

**Last updated:** 2026-04-26  
**OpenClaw Version:** 2026.4.2
