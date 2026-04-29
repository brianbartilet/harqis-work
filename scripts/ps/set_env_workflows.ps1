# set_env_workflows.ps1 — Load app env vars and configure Python paths.
#
# Dot-source this script (don't run it):
#   . .\scripts\ps\set_env_workflows.ps1
#
# Equivalent of scripts/sh/set_env_workflows.sh.

$ErrorActionPreference = 'Stop'

# ── Resolve paths ─────────────────────────────────────────────────────────────
$pathGitRoot = (& git rev-parse --show-toplevel) 2>$null
if (-not $pathGitRoot) {
    Write-Error "Not inside a git repository. Run from harqis-work checkout."
    return
}
$pathScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path

Write-Host "Git root detected: $pathGitRoot"

# ── Load .env\apps.env ────────────────────────────────────────────────────────
$envFile = Join-Path $pathGitRoot ".env\apps.env"

if (Test-Path $envFile) {
    Write-Host "Loading env vars from `"$envFile`"..."
    foreach ($line in (Get-Content $envFile -ErrorAction SilentlyContinue)) {
        if ([string]::IsNullOrWhiteSpace($line)) { continue }
        if ($line.TrimStart().StartsWith('#')) { continue }
        $idx = $line.IndexOf('=')
        if ($idx -lt 1) { continue }
        $key   = $line.Substring(0, $idx).Trim()
        $value = $line.Substring($idx + 1).Trim('"').Trim("'")
        Set-Item -Path "Env:$key" -Value $value
    }
} else {
    Write-Warning ".env file not found at `"$envFile`""
}

# ── Python path ───────────────────────────────────────────────────────────────
$existingPath = $env:PYTHONPATH
$env:PYTHONPATH = "$pathGitRoot;$pathScriptDir;$existingPath".TrimEnd(';')
Write-Host "PYTHONPATH updated to $env:PYTHONPATH"

# ── Application paths ─────────────────────────────────────────────────────────
$env:ROOT_DIRECTORY            = $pathGitRoot
$env:PATH_APP_CONFIG           = $pathGitRoot
$env:PATH_APP_CONFIG_SECRETS   = Join-Path $pathGitRoot ".env"

# ── Celery / Sprout config ────────────────────────────────────────────────────
$env:WORKFLOW_CONFIG = "workflows.config"
Write-Host "WORKFLOW_CONFIG set to $env:WORKFLOW_CONFIG"

$env:APP_CONFIG_FILE = "apps_config.yaml"
Write-Host "APP_CONFIG_FILE set to $env:APP_CONFIG_FILE"

# Celery broker URL — defaults to localhost for the host machine.
# Remote workers override this via the calling shell or .env\apps.env.
if (-not $env:CELERY_BROKER_URL) {
    $env:CELERY_BROKER_URL = "amqp://guest:guest@localhost:5672/"
}
Write-Host "CELERY_BROKER_URL set to $env:CELERY_BROKER_URL"

# Config source — 'local' on the host; remote workers set 'redis' or 'http'.
if (-not $env:CONFIG_SOURCE) { $env:CONFIG_SOURCE = "local" }
