$ErrorActionPreference = "Stop"
$Root = Resolve-Path (Join-Path $PSScriptRoot "..\..\..")
. (Join-Path $PSScriptRoot "Lib.ps1")
Ensure-Repos -Root $Root
Push-Location $Root
try {
    Write-Host "Starting FULL_OBLIVION Raspberry Pi service set: stt, tts, speaker..."
    docker compose --profile stt --profile tts --profile speaker up -d
    docker compose --profile stt --profile tts --profile speaker ps
    Write-Host "Started Raspberry Pi service set."
} finally {
    Pop-Location
}
