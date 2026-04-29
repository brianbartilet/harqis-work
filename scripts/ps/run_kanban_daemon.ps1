# Daemon wrapper for the Kanban orchestrator — invoked by Task Scheduler / Start-Process.
#
# Env vars:
#   KANBAN_NUM_AGENTS      — concurrent in-process agent workers (default: 1)
#   KANBAN_POLL_INTERVAL   — seconds between board polls (default: orchestrator default)
#   KANBAN_PROFILES_DIR    — override profiles directory
#   KANBAN_DRY_RUN         — set to "1" to log actions without invoking Claude
#   KANBAN_PROFILE_FILTER  — restrict to one profile (e.g. "agent:default", "agent:code")
#   KANBAN_HW_LABELS       — comma-separated hw:* labels this orchestrator satisfies;
#                            unset = auto-detect from the host OS (Windows → hw:windows)
$ErrorActionPreference = 'Stop'

$repoRoot = (& git -C $PSScriptRoot rev-parse --show-toplevel)
$env:PYTHONPATH = "$($env:PYTHONPATH);$repoRoot"

. (Join-Path $repoRoot ".venv\Scripts\Activate.ps1")
. (Join-Path $repoRoot "scripts\ps\set_env_workflows.ps1")

$kanbanArgs = @()
if ($env:KANBAN_NUM_AGENTS)      { $kanbanArgs += @('--num-agents',     $env:KANBAN_NUM_AGENTS) }
if ($env:KANBAN_POLL_INTERVAL)   { $kanbanArgs += @('--poll-interval',  $env:KANBAN_POLL_INTERVAL) }
if ($env:KANBAN_PROFILES_DIR)    { $kanbanArgs += @('--profiles-dir',   $env:KANBAN_PROFILES_DIR) }
if ($env:KANBAN_PROFILE_FILTER)  { $kanbanArgs += @('--profile',        $env:KANBAN_PROFILE_FILTER) }
if ($env:KANBAN_HW_LABELS)       { $kanbanArgs += @('--hw',             $env:KANBAN_HW_LABELS) }
if ($env:KANBAN_DRY_RUN -eq '1') { $kanbanArgs += '--dry-run' }

& python -m agents.kanban.orchestrator.local @kanbanArgs
