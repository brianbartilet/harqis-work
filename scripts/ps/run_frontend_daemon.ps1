# Daemon wrapper for the FastAPI frontend — invoked by Task Scheduler / Start-Process.
$ErrorActionPreference = 'Stop'

$repoRoot = (& git -C $PSScriptRoot rev-parse --show-toplevel)
$env:PYTHONPATH = "$($env:PYTHONPATH);$repoRoot;$repoRoot\frontend"

. (Join-Path $repoRoot ".venv\Scripts\Activate.ps1")

# Load env file so FastAPI settings are available
$envFile = Join-Path $repoRoot ".env\apps.env"
if (Test-Path $envFile) {
    foreach ($line in (Get-Content $envFile)) {
        if ([string]::IsNullOrWhiteSpace($line)) { continue }
        if ($line.TrimStart().StartsWith('#')) { continue }
        $idx = $line.IndexOf('=')
        if ($idx -lt 1) { continue }
        $key   = $line.Substring(0, $idx).Trim()
        $value = $line.Substring($idx + 1).Trim('"').Trim("'")
        Set-Item -Path "Env:$key" -Value $value
    }
}

& python (Join-Path $repoRoot "frontend\main.py")
