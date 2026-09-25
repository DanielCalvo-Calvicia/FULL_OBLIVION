$ErrorActionPreference = "Stop"
$Root = Resolve-Path (Join-Path $PSScriptRoot "..\..\..")
. (Join-Path $PSScriptRoot "Lib.ps1")
Ensure-Repos -Root $Root
Push-Location $Root
try {
    Write-Host "Starting FULL_OBLIVION audio-only services: microphone, speaker..."
    docker compose --profile audio up -d
    docker compose --profile audio ps
    Write-Host "Started audio-only services."
} finally {
    Pop-Location
}
