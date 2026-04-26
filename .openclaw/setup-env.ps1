# OpenClaw Environment Setup Script
# This script configures OPENCLAW_CONFIG_PATH and OPENCLAW_STATE_DIR
# to use this sync repo for persistence

param(
    [string]$SyncRepo = "C:\Users\brian\GIT\harqis-work\.openclaw\workspace",
    [string]$Profile = "default",
    [switch]$Permanent,
    [switch]$Help
)

# Display help
if ($Help) {
    Write-Host @"
Usage: .\setup-env.ps1 [options]

Options:
  -SyncRepo <path>     Path to the sync repository (default: ./.openclaw/workspace)
  -Profile <name>      OpenClaw profile name (default: default)
  -Permanent           Save to user environment variables (requires elevation)
  -Help                Display this help message

Examples:
  # Set environment variables for current session
  .\setup-env.ps1

  # Permanently set environment variables to user profile
  .\setup-env.ps1 -Permanent

  # Use a custom sync repo path
  .\setup-env.ps1 -SyncRepo "D:\my-openclaw-sync" -Permanent

Description:
  This script configures OpenClaw to use a specific directory for storing
  configuration and state. This allows you to sync your OpenClaw setup
  across machines.

  Environment Variables:
  - OPENCLAW_CONFIG_PATH: Where OpenClaw reads/writes configuration
  - OPENCLAW_STATE_DIR: Where OpenClaw stores session and runtime state
"@
    exit 0
}

# Validate sync repo exists
if (-not (Test-Path $SyncRepo)) {
    Write-Host "Error: Sync repository path not found: $SyncRepo" -ForegroundColor Red
    exit 1
}

# Ensure directories exist
$configPath = Join-Path $SyncRepo "config"
$statePath = Join-Path $SyncRepo "state"

if (-not (Test-Path $configPath)) {
    New-Item -ItemType Directory -Force -Path $configPath | Out-Null
    Write-Host "Created: $configPath" -ForegroundColor Green
}

if (-not (Test-Path $statePath)) {
    New-Item -ItemType Directory -Force -Path $statePath | Out-Null
    Write-Host "Created: $statePath" -ForegroundColor Green
}

# Set environment variables for current session
$env:OPENCLAW_CONFIG_PATH = $configPath
$env:OPENCLAW_STATE_DIR = $statePath

if ($Profile -ne "default") {
    $env:OPENCLAW_PROFILE = $Profile
}

Write-Host "`nEnvironment variables set for current session:" -ForegroundColor Cyan
Write-Host "  OPENCLAW_CONFIG_PATH = $configPath"
Write-Host "  OPENCLAW_STATE_DIR = $statePath"

if ($Profile -ne "default") {
    Write-Host "  OPENCLAW_PROFILE = $Profile"
}

# Optionally save permanently
if ($Permanent) {
    # Check for admin privileges
    $isAdmin = ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
    
    if (-not $isAdmin) {
        Write-Host "`nError: -Permanent flag requires administrator privileges" -ForegroundColor Red
        Write-Host "Please run PowerShell as Administrator and try again" -ForegroundColor Yellow
        exit 1
    }

    # Set user environment variables
    [Environment]::SetEnvironmentVariable("OPENCLAW_CONFIG_PATH", $configPath, "User")
    [Environment]::SetEnvironmentVariable("OPENCLAW_STATE_DIR", $statePath, "User")
    
    if ($Profile -ne "default") {
        [Environment]::SetEnvironmentVariable("OPENCLAW_PROFILE", $Profile, "User")
    }

    Write-Host "`nEnvironment variables saved permanently to user profile" -ForegroundColor Green
    Write-Host "Note: You may need to restart applications for new environment variables to take effect" -ForegroundColor Yellow
}

Write-Host "`nSetup complete!" -ForegroundColor Green
Write-Host "OpenClaw will now use this sync repo for configuration and state persistence" -ForegroundColor Cyan
