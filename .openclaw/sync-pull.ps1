# OpenClaw Sync - Auto Pull Script (Windows PowerShell)
# Pull latest changes from harqis-openclaw-sync
# Run every 30 minutes via cron or task scheduler

param(
    [string]$RepoPath = "C:\Users\brian\GIT\harqis-openclaw-sync"
)

Write-Host "=== OpenClaw Sync: Pull Changes ===" -ForegroundColor Cyan
Write-Host "Repository: $RepoPath"
Write-Host "Time: $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')"
Write-Host ""

# Check if repo exists
if (-not (Test-Path $RepoPath)) {
    Write-Host "Error: Repository not found at $RepoPath" -ForegroundColor Red
    exit 1
}

try {
    # Change to repo directory
    Set-Location $RepoPath
    
    # Fetch first to check for changes
    Write-Host "Fetching from origin..." -ForegroundColor Yellow
    git fetch origin main
    
    # Check if local is behind
    $local = git rev-parse HEAD
    $remote = git rev-parse origin/main
    
    if ($local -eq $remote) {
        Write-Host "✓ Already up to date" -ForegroundColor Green
        exit 0
    }
    
    # Pull changes
    Write-Host "Pulling latest changes..." -ForegroundColor Yellow
    git pull origin main
    
    Write-Host ""
    Write-Host "✓ Pull complete!" -ForegroundColor Green
    Write-Host "Latest changes from harqis-openclaw-sync applied"
}
catch {
    Write-Host "Error: $_" -ForegroundColor Red
    exit 1
}
