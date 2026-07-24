#!/usr/bin/env pwsh
<#
.SYNOPSIS
Fail-open Windows launcher for the Codex HFL lifecycle hooks.

.DESCRIPTION
Reads the Codex hook JSON envelope from stdin without inspecting or logging it,
resolves the repository interpreter from this script's location, and forwards
the envelope to capture_session_event.py. Launcher failures never fail the
Codex turn; the durable audit retry path handles missing captures separately.

.EXAMPLE
Get-Content hook.json -Raw |
    powershell -NoProfile -File scripts/agents/hfl/capture_session_hook.ps1
#>

[CmdletBinding()]
param(
    [ValidateSet("codex", "claude-code", "hermes", "openclaw")]
    [string]$Surface = "codex"
)

$ErrorActionPreference = "Stop"

try {
    $repoRoot = (Resolve-Path -LiteralPath (
        Join-Path $PSScriptRoot "..\..\.."
    )).Path
    $python = Join-Path $repoRoot ".venv\Scripts\python.exe"
    $capture = Join-Path $repoRoot "scripts\agents\hfl\capture_session_event.py"

    if (-not (Test-Path -LiteralPath $python -PathType Leaf)) {
        throw "Repository Python interpreter is unavailable."
    }
    if (-not (Test-Path -LiteralPath $capture -PathType Leaf)) {
        throw "HFL session capture entry point is unavailable."
    }

    $payload = [Console]::In.ReadToEnd()
    $payload | & $python $capture --surface $Surface --hook
}
catch {
    # Audit capture is observational. It must never block or mark a Codex turn
    # as failed, and the hook must not echo payloads or exception details.
}

exit 0
