param(
    [string[]]$Profiles = @("full")
)

$ErrorActionPreference = "Stop"
$Root = Resolve-Path (Join-Path $PSScriptRoot "..\..\..")
$Args = @()
foreach ($Profile in $Profiles) {
    $Args += @("--profile", $Profile)
}

Push-Location $Root
try {
    Write-Host "Stopping FULL_OBLIVION profiles: $($Profiles -join ', ')"
    docker compose @Args down
    Write-Host "Stopped FULL_OBLIVION profiles: $($Profiles -join ', ')"
} finally {
    Pop-Location
}
