# Daemon wrapper for the Celery Beat scheduler — invoked by Task Scheduler / Start-Process.
$ErrorActionPreference = 'Stop'

$repoRoot = (& git -C $PSScriptRoot rev-parse --show-toplevel)
. (Join-Path $repoRoot ".venv\Scripts\Activate.ps1")
. (Join-Path $repoRoot "scripts\ps\set_env_workflows.ps1")

& python (Join-Path $repoRoot "run_workflows.py") scheduler
