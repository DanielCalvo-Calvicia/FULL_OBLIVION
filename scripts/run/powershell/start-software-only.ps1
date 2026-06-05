$ErrorActionPreference = "Stop"
$Root = Resolve-Path (Join-Path $PSScriptRoot "..\..\..")
. (Join-Path $PSScriptRoot "Lib.ps1")
Ensure-Repos -Root $Root
Push-Location $Root
try {
    Write-Host "Starting FULL_OBLIVION software-only services: stt, tts..."
    docker compose --profile stt --profile tts up -d
    docker compose --profile stt --profile tts ps
    Write-Host "Started software-only services."
} finally {
    Pop-Location
}
