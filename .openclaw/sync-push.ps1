# OpenClaw Sync - Auto Push Script (Windows PowerShell)
# Commit and push changes to harqis-openclaw-sync
# Run every 15 minutes via cron or task scheduler

param(
    [string]$RepoPath = "C:\Users\brian\GIT\harqis-openclaw-sync",
    [string]$CommitMessage = "sync: auto-commit workspace changes"
)

Write-Host "=== OpenClaw Sync: Push Changes ===" -ForegroundColor Cyan
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
    
    # Check git status
    Write-Host "Checking for changes..." -ForegroundColor Yellow
    $status = git status --porcelain
    
    if ([string]::IsNullOrWhiteSpace($status)) {
        Write-Host "✓ No changes to commit" -ForegroundColor Green
        exit 0
    }
    
    # Stage all changes
    Write-Host "Staging changes..." -ForegroundColor Yellow
    git add -A
    
    # Commit
    $timestamp = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
    $fullMessage = "$CommitMessage [$timestamp]"
    Write-Host "Committing: $fullMessage" -ForegroundColor Yellow
    git commit -m $fullMessage
    
    # Push
    Write-Host "Pushing to origin..." -ForegroundColor Yellow
    git push origin main
    
    Write-Host ""
    Write-Host "✓ Sync complete!" -ForegroundColor Green
    Write-Host "Changes pushed to harqis-openclaw-sync"
}
catch {
    Write-Host "Error: $_" -ForegroundColor Red
    exit 1
}
