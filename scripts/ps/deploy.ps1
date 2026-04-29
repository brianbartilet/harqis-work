<#
.SYNOPSIS
    deploy.ps1 — Bring up (or tear down) the harqis-work platform on Windows.

.DESCRIPTION
    Roles:
      host   — the always-on hub: Docker stack + Beat scheduler + worker(s) + frontend
               + MCP daemon + Kanban orchestrator + Flower (Celery monitor).
               The Kanban orchestrator also acts as 1 in-process agent worker.
      node   — a remote worker that connects to the host's broker. Runs Celery
               worker(s) only (no Docker, no scheduler, no frontend).

    Background processes are launched via Start-Process with -WindowStyle Hidden
    and their PIDs are tracked in <repo>\.run\<service>.pid for clean teardown.
    For production / always-on use, register each daemon as a Scheduled Task
    (see -Register flag).

.EXAMPLE
    .\scripts\ps\deploy.ps1 -Role host
    .\scripts\ps\deploy.ps1 -Role host -Queues "default,adhoc,tcg"
    .\scripts\ps\deploy.ps1 -Role node -Queues "hud,tcg,default"
    .\scripts\ps\deploy.ps1 -Role host -Down
    .\scripts\ps\deploy.ps1 -Role host -Register   # register all as Scheduled Tasks
#>
[CmdletBinding()]
param(
    [Parameter(Mandatory=$false)]
    [ValidateSet('host','node')]
    [string]$Role = 'host',

    [Parameter(Mandatory=$false)]
    [Alias('q')]
    [string]$Queues = 'default',

    [switch]$Down,
    [switch]$DockerOnly,
    [switch]$NoFrontend,
    [switch]$NoMcp,
    [switch]$NoKanban,
    [switch]$NoFlower,
    [switch]$Register,
    [int]$NumAgents = 1
)

$ErrorActionPreference = 'Stop'

# ── Resolve paths ─────────────────────────────────────────────────────────────
$repoRoot = (& git -C $PSScriptRoot rev-parse --show-toplevel)
$runDir = Join-Path $repoRoot ".run"
if (-not (Test-Path $runDir)) { New-Item -ItemType Directory -Path $runDir | Out-Null }

# Strip whitespace from queues — must look like "q1,q2,q3"
$Queues = ($Queues -replace '\s', '')
$env:WORKFLOW_QUEUE = $Queues
$env:KANBAN_NUM_AGENTS = "$NumAgents"

# ── Service definitions (label → script + role visibility) ───────────────────
$services = @(
    @{ Label='work.harqis.scheduler'; Script='run_scheduler_daemon.ps1'; Roles='host'; Skip=$false }
    @{ Label='work.harqis.worker';    Script='run_worker_daemon.ps1';    Roles='host,node'; Skip=$false }
    @{ Label='work.harqis.frontend';  Script='run_frontend_daemon.ps1';  Roles='host'; Skip=$NoFrontend }
    @{ Label='work.harqis.mcp';       Script='run_mcp_daemon.ps1';       Roles='host'; Skip=$NoMcp }
    @{ Label='work.harqis.kanban';    Script='run_kanban_daemon.ps1';    Roles='host'; Skip=$NoKanban }
    @{ Label='work.harqis.flower';    Script='run_flower_daemon.ps1';    Roles='host'; Skip=$NoFlower }
)

# ── Load secrets from .env\apps.env (for docker-compose env interpolation) ───
$envFile = Join-Path $repoRoot ".env\apps.env"
if (Test-Path $envFile) {
    Write-Host "Loading secrets from $envFile..."
    foreach ($line in (Get-Content $envFile)) {
        if ([string]::IsNullOrWhiteSpace($line)) { continue }
        if ($line.TrimStart().StartsWith('#')) { continue }
        $idx = $line.IndexOf('=')
        if ($idx -lt 1) { continue }
        $key   = $line.Substring(0, $idx).Trim()
        $value = $line.Substring($idx + 1).Trim('"').Trim("'")
        Set-Item -Path "Env:$key" -Value $value
    }
} else {
    Write-Warning "No secrets source found at $envFile."
}

# ── Helpers ───────────────────────────────────────────────────────────────────
function Test-PidAlive($pid) {
    if (-not $pid) { return $false }
    try { $null = Get-Process -Id $pid -ErrorAction Stop; return $true }
    catch { return $false }
}

function Start-Daemon($svc) {
    $pidFile = Join-Path $runDir "$($svc.Label).pid"
    if (Test-Path $pidFile) {
        $existingPid = Get-Content $pidFile -ErrorAction SilentlyContinue
        if (Test-PidAlive $existingPid) {
            Write-Host "  Already running: $($svc.Label) (PID $existingPid)"
            return
        }
    }
    $scriptPath = Join-Path $repoRoot "scripts\ps\$($svc.Script)"
    $logPath    = Join-Path $repoRoot "logs\$($svc.Label).log"
    $logDir     = Split-Path $logPath -Parent
    if (-not (Test-Path $logDir)) { New-Item -ItemType Directory -Path $logDir | Out-Null }

    $proc = Start-Process powershell `
        -ArgumentList @('-NoProfile','-ExecutionPolicy','Bypass','-File',"`"$scriptPath`"") `
        -WindowStyle Hidden -PassThru `
        -RedirectStandardOutput $logPath -RedirectStandardError "$logPath.err"
    $proc.Id | Out-File -FilePath $pidFile -Encoding ascii
    Write-Host "  Started: $($svc.Label) (PID $($proc.Id))  →  $logPath"
}

function Stop-Daemon($svc) {
    $pidFile = Join-Path $runDir "$($svc.Label).pid"
    if (-not (Test-Path $pidFile)) { return }
    $pid = Get-Content $pidFile -ErrorAction SilentlyContinue
    if (Test-PidAlive $pid) {
        Stop-Process -Id $pid -Force -ErrorAction SilentlyContinue
        Write-Host "  Stopped: $($svc.Label) (PID $pid)"
    }
    Remove-Item $pidFile -ErrorAction SilentlyContinue
}

function Register-DaemonTask($svc) {
    $scriptPath = Join-Path $repoRoot "scripts\ps\$($svc.Script)"
    $action  = New-ScheduledTaskAction -Execute 'powershell' `
        -Argument "-NoProfile -ExecutionPolicy Bypass -File `"$scriptPath`""
    $trigger = New-ScheduledTaskTrigger -AtStartup
    $settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries `
        -StartWhenAvailable -RestartInterval (New-TimeSpan -Minutes 1) -RestartCount 999
    Register-ScheduledTask -TaskName $svc.Label -Action $action -Trigger $trigger `
        -Settings $settings -Force -RunLevel Highest | Out-Null
    Write-Host "  Registered: $($svc.Label) (Scheduled Task, runs at startup)"
}

function Unregister-DaemonTask($svc) {
    $existing = Get-ScheduledTask -TaskName $svc.Label -ErrorAction SilentlyContinue
    if ($existing) {
        Unregister-ScheduledTask -TaskName $svc.Label -Confirm:$false
        Write-Host "  Unregistered: $($svc.Label)"
    }
}

# ── Filter services for this role ────────────────────────────────────────────
$activeSvcs = $services | Where-Object {
    -not $_.Skip -and ($_.Roles -split ',') -contains $Role
}

# ── Docker compose (host only) ───────────────────────────────────────────────
function Invoke-DockerCompose($action) {
    if ($Role -ne 'host') {
        Write-Host "[node] Skipping Docker — broker is on the host."
        return
    }
    Push-Location $repoRoot
    try {
        if ($action -eq 'up') {
            Write-Host "[host] Starting Docker services..."
            & docker compose up -d
            & docker compose ps --format "table {{.Name}}`t{{.Status}}`t{{.Ports}}"
        } elseif ($action -eq 'down') {
            Write-Host "Stopping Docker services..."
            & docker compose down
        }
    } finally { Pop-Location }
}

# ── Execute ──────────────────────────────────────────────────────────────────
if ($Down) {
    Write-Host "==> Tearing down role=$Role"
    foreach ($svc in $activeSvcs) {
        Stop-Daemon $svc
        if ($Register) { Unregister-DaemonTask $svc }
    }
    if (-not $DockerOnly) { Invoke-DockerCompose -action down }
    Write-Host "All services stopped for role=$Role."
    exit 0
}

# ── Up path ──────────────────────────────────────────────────────────────────
Write-Host "==> Deploy role=$Role  queues=$Queues  num-agents=$NumAgents"

Invoke-DockerCompose -action up

if (-not $DockerOnly) {
    Write-Host ""
    foreach ($svc in $activeSvcs) {
        if ($Register) { Register-DaemonTask $svc }
        Start-Daemon $svc
    }
}

Write-Host ""
if ($Role -eq 'host') {
    $components = @('docker','scheduler',"worker(queues=$Queues)")
    if (-not $NoFrontend) { $components += 'frontend' }
    if (-not $NoMcp)      { $components += 'mcp' }
    if (-not $NoKanban)   { $components += 'kanban' }
    if (-not $NoFlower)   { $components += 'flower' }
    Write-Host "[host] Deploy complete."
    Write-Host "  Components: $($components -join ', ')"
    Write-Host "  Frontend:   http://localhost:8000"
    if (-not $NoFlower)   { Write-Host "  Flower:     http://localhost:5555  (basic-auth: `$FLOWER_USER:`$FLOWER_PASSWORD)" }
    Write-Host "  Logs:       $repoRoot\logs\work.harqis.*.log"
} else {
    $broker = if ($env:CELERY_BROKER_URL) { $env:CELERY_BROKER_URL } else { '(unset — set CELERY_BROKER_URL!)' }
    Write-Host "[node] Worker attached to broker $broker"
    Write-Host "  Queues:   $Queues"
}
Write-Host "Stop with: .\scripts\ps\deploy.ps1 -Role $Role -Down"
