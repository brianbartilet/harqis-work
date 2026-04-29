# Daemon wrapper for the Celery Flower monitoring UI — invoked by Task Scheduler / Start-Process.
#
# Env vars:
#   FLOWER_USER     — basic-auth username (required)
#   FLOWER_PASSWORD — basic-auth password (required)
#                     Legacy fallback: FLOWER_PASS is also accepted if FLOWER_PASSWORD is unset.
#   FLOWER_PORT     — TCP port (default: 5555)
#   FLOWER_ADDRESS  — bind address (default: 127.0.0.1; set 0.0.0.0 to expose over Tailscale)
$ErrorActionPreference = 'Stop'

$repoRoot = (& git -C $PSScriptRoot rev-parse --show-toplevel)
$env:PYTHONPATH = "$($env:PYTHONPATH);$repoRoot"

. (Join-Path $repoRoot ".venv\Scripts\Activate.ps1")
. (Join-Path $repoRoot "scripts\ps\set_env_workflows.ps1")

# Canonical name is FLOWER_PASSWORD (matches .env\apps.env). Fall back to FLOWER_PASS for legacy.
if (-not $env:FLOWER_PASSWORD) { $env:FLOWER_PASSWORD = $env:FLOWER_PASS }
if (-not $env:FLOWER_PORT)     { $env:FLOWER_PORT = '5555' }
if (-not $env:FLOWER_ADDRESS)  { $env:FLOWER_ADDRESS = '127.0.0.1' }

if (-not $env:FLOWER_USER -or -not $env:FLOWER_PASSWORD) {
    Write-Error "FLOWER_USER and FLOWER_PASSWORD must be set in .env\apps.env"
    exit 1
}

Write-Host "Starting Flower on $($env:FLOWER_ADDRESS):$($env:FLOWER_PORT) (auth: $($env:FLOWER_USER))"
& python -m celery -A core.apps.sprout.app.celery:SPROUT flower `
    --port="$env:FLOWER_PORT" `
    --address="$env:FLOWER_ADDRESS" `
    --basic-auth="$($env:FLOWER_USER):$($env:FLOWER_PASSWORD)"
