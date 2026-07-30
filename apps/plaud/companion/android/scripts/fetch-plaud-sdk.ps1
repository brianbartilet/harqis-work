param(
    [string]$Destination
)

$ErrorActionPreference = "Stop"
$commit = "359efc913672a73de8edde0ab088e5684e2be611"
$expected = "7900F462744DB7EFC6A36C549925E2E3B5072818F3E793AE4AA90BFFD5B67F21"
$projectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
if (-not $Destination) {
    $Destination = Join-Path $projectRoot "app/libs/plaud-sdk.aar"
}
$destinationParent = Split-Path -Parent $Destination
New-Item -ItemType Directory -Path $destinationParent -Force | Out-Null
$url = "https://raw.githubusercontent.com/Plaud-AI/plaud-sdk-public/$commit/sdk/android/plaud-sdk.aar"

Write-Host "Downloading PLAUD Android SDK at $commit ..."
Invoke-WebRequest -Uri $url -OutFile $Destination
$actual = (Get-FileHash -Algorithm SHA256 -LiteralPath $Destination).Hash
if ($actual -ne $expected) {
    Remove-Item -LiteralPath $Destination -Force
    throw "PLAUD SDK checksum mismatch. Expected $expected, got $actual."
}
Write-Host "Verified $Destination ($actual)"
