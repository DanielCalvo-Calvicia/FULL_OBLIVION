param(
    [Parameter(ValueFromRemainingArguments = $true)]
    [string[]]$Services
)

$ErrorActionPreference = "Stop"

$Root = Resolve-Path (Join-Path $PSScriptRoot "..\..")
$AllServices = @("brain", "microphone", "stt", "tts", "speaker")

if (-not $Services -or $Services.Count -eq 0) {
    $Services = $AllServices
}

Push-Location $Root
try {
    docker compose build --no-cache @Services
    docker compose --profile full up -d @Services
} finally {
    Pop-Location
}

Write-Host "Rebuild complete for: $($Services -join ', ')"
