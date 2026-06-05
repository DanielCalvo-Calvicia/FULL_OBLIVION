$ErrorActionPreference = "Stop"
$Root = Resolve-Path (Join-Path $PSScriptRoot "..\..\..")
. (Join-Path $PSScriptRoot "Lib.ps1")
Ensure-Repos -Root $Root
Push-Location $Root
try {
    Write-Host "Starting FULL_OBLIVION full local stack..."
    docker compose --profile full up -d
    docker compose --profile full ps
    Write-Host "Started full local stack."
} finally {
    Pop-Location
}
