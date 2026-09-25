param(
    [string[]]$Profiles = @("full")
)

$ErrorActionPreference = "Stop"
$Root = Resolve-Path (Join-Path $PSScriptRoot "..\..\..")
. (Join-Path $PSScriptRoot "Lib.ps1")
Ensure-Repos -Root $Root
$Args = @()
foreach ($Profile in $Profiles) {
    $Args += @("--profile", $Profile)
}

Push-Location $Root
try {
    Write-Host "Restarting FULL_OBLIVION profiles: $($Profiles -join ', ')"
    docker compose @Args down
    docker compose @Args up -d
    docker compose @Args ps
} finally {
    Pop-Location
}
