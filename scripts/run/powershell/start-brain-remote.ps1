$ErrorActionPreference = "Stop"
$Root = Resolve-Path (Join-Path $PSScriptRoot "..\..\..")
. (Join-Path $PSScriptRoot "Lib.ps1")
Ensure-Repos -Root $Root
Push-Location $Root
try {
    Write-Host "Starting FULL_OBLIVION brain container with configured remote service URLs..."
    Write-Host "MICROPHONE_BASE_URL=$($env:MICROPHONE_BASE_URL)"
    Write-Host "STT_BASE_URL=$($env:STT_BASE_URL)"
    Write-Host "TTS_BASE_URL=$($env:TTS_BASE_URL)"
    Write-Host "SPEAKER_BASE_URL=$($env:SPEAKER_BASE_URL)"
    docker compose --profile brain up -d
    docker compose --profile brain ps
    Write-Host "Started brain."
} finally {
    Pop-Location
}
