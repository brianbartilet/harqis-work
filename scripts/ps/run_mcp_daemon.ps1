# Daemon wrapper for the harqis-work MCP server.
#
# The MCP server speaks stdio to its client (typically Claude Desktop spawns
# this process directly). This wrapper exists for two cases:
#   1. SSH remote access — `ssh host pwsh -File C:\harqis-work\scripts\ps\run_mcp_daemon.ps1`
#   2. HTTP transport (when configured upstream) under Task Scheduler
$ErrorActionPreference = 'Stop'

$repoRoot = (& git -C $PSScriptRoot rev-parse --show-toplevel)
$env:PYTHONPATH = "$($env:PYTHONPATH);$repoRoot"

. (Join-Path $repoRoot ".venv\Scripts\Activate.ps1")

if (-not $env:APP_CONFIG_FILE) { $env:APP_CONFIG_FILE = "apps_config.yaml" }

& python (Join-Path $repoRoot "mcp\server.py")
