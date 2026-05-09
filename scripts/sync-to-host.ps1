#!/usr/bin/env pwsh
# Push a configured set of files to a remote harqis-work checkout via tar | ssh.
# One password prompt: bundles everything into a single tar stream piped over ssh.
#
# All identifying info (machine keys, hosts, paths, file list) lives in
# machines.local.toml (gitignored). This script ships no defaults of its own.
#
# Required toml shape:
#   [sync]
#   default_machine = "<machine-key>"             # used when -MachineKey is omitted
#   items           = ["<path>", "<path>", ...]   # repo-relative paths to push
#
#   [ssh.<machine-key>]
#   user = "<remote-user>"
#   host = "<reachable-hostname>"
#   path = "<remote-destination>"
#
# Usage:
#   ./scripts/sync-to-host.ps1
#   ./scripts/sync-to-host.ps1 -MachineKey <key>
#   ./scripts/sync-to-host.ps1 -SshTarget user@host -RemotePath '~/elsewhere'   # explicit override
#   ./scripts/sync-to-host.ps1 -List
#   ./scripts/sync-to-host.ps1 -DryRun

[CmdletBinding()]
param(
    [string]$MachineKey,
    [string]$SshTarget,
    [string]$RemotePath,
    [switch]$List,
    [switch]$DryRun,
    [switch]$Check
)

$ErrorActionPreference = 'Stop'

$repoRoot = Split-Path -Parent $PSScriptRoot
Set-Location $repoRoot

$tomlPath = Join-Path $repoRoot 'machines.local.toml'
if (-not (Test-Path -LiteralPath $tomlPath)) {
    throw "machines.local.toml not found at $tomlPath. Create it with [sync] and [ssh.*] blocks (see script header)."
}
$tomlContent = Get-Content -Raw -LiteralPath $tomlPath

function Get-Section {
    param([string]$Header)
    $escaped = [regex]::Escape($Header)
    $m = [regex]::Match($tomlContent, "(?ms)^\[$escaped\]\s*\r?\n(.*?)(?=^\[|\z)")
    if ($m.Success) { return $m.Groups[1].Value }
    return $null
}

function Get-StringField {
    param([string]$Body, [string]$Name)
    $m = [regex]::Match($Body, "(?m)^\s*$Name\s*=\s*`"([^`"]+)`"")
    if ($m.Success) { return $m.Groups[1].Value }
    return $null
}

function Get-StringArrayField {
    param([string]$Body, [string]$Name)
    $m = [regex]::Match($Body, "(?ms)^\s*$Name\s*=\s*\[(.*?)\]")
    if (-not $m.Success) { return @() }
    $inner = $m.Groups[1].Value
    return [regex]::Matches($inner, '"([^"]+)"') | ForEach-Object { $_.Groups[1].Value }
}

if ($List) {
    Write-Host "Configured [ssh.*] targets in machines.local.toml:"
    $matches = [regex]::Matches($tomlContent, "(?m)^\[ssh\.([^\]]+)\]")
    if ($matches.Count -eq 0) { Write-Host "  (none)"; return }
    foreach ($mm in $matches) {
        $key = $mm.Groups[1].Value
        $body = Get-Section "ssh.$key"
        $u = Get-StringField $body 'user'
        $h = Get-StringField $body 'host'
        $p = Get-StringField $body 'path'
        Write-Host ("  - {0,-24} {1}@{2}:{3}" -f $key, $u, $h, $p)
    }
    return
}

$syncBody = Get-Section 'sync'
if (-not $syncBody) {
    throw "[sync] section missing from machines.local.toml. Add 'default_machine' and 'items' (see script header)."
}

if (-not $MachineKey) {
    $MachineKey = Get-StringField $syncBody 'default_machine'
    if (-not $MachineKey) {
        throw "[sync] default_machine is not set; pass -MachineKey <key> or add it to machines.local.toml."
    }
}

$items = Get-StringArrayField $syncBody 'items'
if ($items.Count -eq 0) {
    throw "[sync] items is empty or missing; populate it in machines.local.toml."
}

$sshBody = Get-Section "ssh.$MachineKey"
if (-not $sshBody) {
    throw "[ssh.$MachineKey] not found in machines.local.toml. Run with -List to see configured targets."
}

if (-not $SshTarget) {
    $u = Get-StringField $sshBody 'user'
    $h = Get-StringField $sshBody 'host'
    if (-not $u -or -not $h) { throw "[ssh.$MachineKey] is missing 'user' or 'host'." }
    $SshTarget = "$u@$h"
}
if (-not $RemotePath) {
    $RemotePath = Get-StringField $sshBody 'path'
    if (-not $RemotePath) { throw "[ssh.$MachineKey] is missing 'path' (and no -RemotePath given)." }
}

foreach ($item in $items) {
    if (-not (Test-Path -LiteralPath $item)) {
        throw "Missing source: $item (cwd=$repoRoot)"
    }
}

Write-Host "Source repo : $repoRoot"
Write-Host "Machine key : $MachineKey"
Write-Host "SSH target  : $SshTarget"
Write-Host "Remote path : $RemotePath"
Write-Host "Items       :"
foreach ($item in $items) { Write-Host "  - $item" }

# Remote command: extract verbosely, then list the destination so the user gets
# ground truth on one connection (no second password prompt).
# Single-quoted PS string so 2>&1 stays literal text for the remote shell.
$verifyList = ($items | ForEach-Object { "$RemotePath/$_" }) -join ' '
$remoteCmd  = 'mkdir -p ' + $RemotePath + ' && tar -xvf - -C ' + $RemotePath +
              " && echo '---POST-SYNC LISTING---' && ls -la " + $verifyList + ' 2>' + '&1'

if ($Check) {
    $checkCmd = 'echo OK && uname -a && pwd && ls -d ' + $RemotePath + ' 2>' + '&1'
    Write-Host "Connectivity check -> $SshTarget" -ForegroundColor Cyan
    Write-Host "  (one password prompt; runs: $checkCmd)"
    & ssh -o ConnectTimeout=8 $SshTarget $checkCmd
    if ($LASTEXITCODE -ne 0) {
        Write-Host "`nssh exited $LASTEXITCODE -- connectivity or auth failed." -ForegroundColor Red
        exit $LASTEXITCODE
    }
    Write-Host "`nConnectivity OK." -ForegroundColor Green
    return
}

if ($DryRun) {
    Write-Host "`n[dry-run] Would run:" -ForegroundColor Yellow
    Write-Host ('  tar -cf [tmpfile] {0}' -f ($items -join ' '))
    Write-Host ('  ssh {0} "{1}" [stdin: tmpfile]' -f $SshTarget, $remoteCmd)
    return
}

# Use Windows's built-in bsdtar explicitly — `tar` on PATH often resolves to
# Git-for-Windows' GNU tar, which mangles Windows paths (treats `C:` as an
# rsh-style host) and produces archives the remote can't parse.
$tarExe = Join-Path $env:WINDIR 'System32\tar.exe'
if (-not (Test-Path -LiteralPath $tarExe)) {
    throw "bsdtar not found at $tarExe (Windows 10 1803+ ships it). Install or adjust the script."
}

# Strategy: tar to a temp file (avoids PowerShell's text-mode pipeline that
# corrupts binary streams), then feed that file into ssh's stdin via .NET's
# Process API (avoids cmd.exe's quirky quote handling around `< file` with
# multiple double-quoted arguments).
$tarFile = Join-Path ([System.IO.Path]::GetTempPath()) "sync-to-host-$([guid]::NewGuid()).tar"

try {
    Write-Host "`nBuilding archive at $tarFile ..." -ForegroundColor Cyan
    & $tarExe -cf $tarFile @items
    if ($LASTEXITCODE -ne 0) { throw "tar failed (exit $LASTEXITCODE)" }

    $tarSize = (Get-Item -LiteralPath $tarFile).Length
    Write-Host ("  archive size: {0:N0} bytes" -f $tarSize)
    Write-Host "  archive contents:"
    & $tarExe -tf $tarFile | ForEach-Object { Write-Host "    $_" }

    Write-Host "`nStreaming archive to $SshTarget ..." -ForegroundColor Cyan
    $sshCmd = Get-Command ssh -ErrorAction Stop
    $psi = [System.Diagnostics.ProcessStartInfo]::new()
    $psi.FileName = $sshCmd.Source
    $psi.Arguments = '"{0}" "{1}"' -f $SshTarget, $remoteCmd
    $psi.UseShellExecute = $false
    $psi.RedirectStandardInput = $true   # binary stdin from .NET FileStream

    $proc = [System.Diagnostics.Process]::Start($psi)
    $tarStream = [System.IO.File]::OpenRead($tarFile)
    try {
        $tarStream.CopyTo($proc.StandardInput.BaseStream)
    }
    finally {
        $tarStream.Dispose()
        $proc.StandardInput.Close()
    }
    $proc.WaitForExit()

    if ($proc.ExitCode -ne 0) { throw "ssh/tar-extract failed (exit $($proc.ExitCode))" }
}
finally {
    Remove-Item -LiteralPath $tarFile -ErrorAction SilentlyContinue
}

Write-Host "`nDone." -ForegroundColor Green
