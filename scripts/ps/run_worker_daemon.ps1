# Daemon wrapper for a Celery worker — invoked by Task Scheduler / Start-Process.
#
# Env vars:
#   WORKFLOW_QUEUE — comma-separated queue list, e.g. "default" or "hud,tcg,default".
#                    Defaults to "default" if not set. Celery's -Q natively accepts
#                    multiple queues, so a single process listens to all of them.
$ErrorActionPreference = 'Stop'

$repoRoot = (& git -C $PSScriptRoot rev-parse --show-toplevel)
. (Join-Path $repoRoot ".venv\Scripts\Activate.ps1")
. (Join-Path $repoRoot "scripts\ps\set_env_workflows.ps1")

if (-not $env:WORKFLOW_QUEUE) { $env:WORKFLOW_QUEUE = "default" }

Write-Host "Starting worker on queue(s): $env:WORKFLOW_QUEUE"
& python (Join-Path $repoRoot "run_workflows.py") worker
