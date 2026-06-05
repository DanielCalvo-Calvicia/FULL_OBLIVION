$ErrorActionPreference = "Stop"
$Root = Resolve-Path (Join-Path $PSScriptRoot "..\..\..")
. (Join-Path $PSScriptRoot "Lib.ps1")
Ensure-Repos -Root $Root
Push-Location $Root
try {
    Write-Host "Starting FULL_OBLIVION brain container with configured remote service URLs..."
    Write-Host "BRAIN_MICROPHONE_BASE_URL=$($env:BRAIN_MICROPHONE_BASE_URL)"
    Write-Host "BRAIN_STT_BASE_URL=$($env:BRAIN_STT_BASE_URL)"
    Write-Host "BRAIN_TTS_BASE_URL=$($env:BRAIN_TTS_BASE_URL)"
    Write-Host "BRAIN_SPEAKER_BASE_URL=$($env:BRAIN_SPEAKER_BASE_URL)"
    docker compose --profile brain up -d
    docker compose --profile brain ps
    Write-Host "Started brain."
} finally {
    Pop-Location
}
