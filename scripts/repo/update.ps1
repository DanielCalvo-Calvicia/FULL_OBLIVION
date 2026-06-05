param(
    [switch]$Rebuild
)

$ErrorActionPreference = "Stop"

$Root = Resolve-Path (Join-Path $PSScriptRoot "..\..")
$ReposDir = Join-Path $Root "repos"
$DockerfilesDir = Join-Path $Root "dockerfiles"

$Services = @(
    @{ Name = "brain_microservice"; Dockerfile = "brain.Dockerfile" },
    @{ Name = "microphone_microservice"; Dockerfile = "microphone.Dockerfile" },
    @{ Name = "stt_microservice"; Dockerfile = "stt.Dockerfile" },
    @{ Name = "tts_microservice"; Dockerfile = "tts.Dockerfile" },
    @{ Name = "speaker_microservice"; Dockerfile = "speaker.Dockerfile" }
)

foreach ($Service in $Services) {
    $Repo = Join-Path $ReposDir $Service.Name
    if (-not (Test-Path $Repo)) {
        Write-Host "Missing repo, skipping update: $($Service.Name)"
        continue
    }

    Write-Host "Updating $($Service.Name)..."
    Remove-Item -Force -ErrorAction SilentlyContinue (Join-Path $Repo "Dockerfile")
    Remove-Item -Force -ErrorAction SilentlyContinue (Join-Path $Repo ".dockerignore")

    Push-Location $Repo
    try {
        git pull --ff-only
    } finally {
        Pop-Location
    }

    Copy-Item -Force (Join-Path $DockerfilesDir $Service.Dockerfile) (Join-Path $Repo "Dockerfile")
    Copy-Item -Force (Join-Path $DockerfilesDir ".dockerignore") (Join-Path $Repo ".dockerignore")
}

if ($Rebuild) {
    Push-Location $Root
    try {
        docker compose --profile full build
    } finally {
        Pop-Location
    }
}

Write-Host "Update complete."
