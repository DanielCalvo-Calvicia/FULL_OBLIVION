param(
    [switch]$SkipBuild
)

$ErrorActionPreference = "Stop"

$Root = Resolve-Path (Join-Path $PSScriptRoot "..\..")
$ReposDir = Join-Path $Root "repos"
$DockerfilesDir = Join-Path $Root "dockerfiles"

$Services = @(
    @{ Name = "brain_microservice"; Git = "https://github.com/DanielCalvo-Calvicia/brain_microservice.git"; Branch = "main"; Dockerfile = "brain.Dockerfile" },
    @{ Name = "microphone_microservice"; Git = "https://github.com/DanielCalvo-Calvicia/microphone_microservice.git"; Branch = "main"; Dockerfile = "microphone.Dockerfile" },
    @{ Name = "stt_microservice"; Git = "https://github.com/DanielCalvo-Calvicia/stt_microservice.git"; Branch = "main"; Dockerfile = "stt.Dockerfile" },
    @{ Name = "tts_microservice"; Git = "https://github.com/DanielCalvo-Calvicia/tts_microservice.git"; Branch = "main"; Dockerfile = "tts.Dockerfile" },
    @{ Name = "speaker_microservice"; Git = "https://github.com/DanielCalvo-Calvicia/speaker_microservice.git"; Branch = "main"; Dockerfile = "speaker.Dockerfile" }
)

New-Item -ItemType Directory -Force -Path $ReposDir | Out-Null

$Failures = @()
foreach ($Service in $Services) {
    $Target = Join-Path $ReposDir $Service.Name
    try {
        if (-not (Test-Path $Target)) {
            Write-Host "Cloning $($Service.Name)..."
            git clone --branch $Service.Branch $Service.Git $Target
        } else {
            Write-Host "Repository exists, updating $($Service.Name) to $($Service.Branch)..."
            Push-Location $Target
            try {
                $Status = git status --porcelain -- . ":(exclude)Dockerfile" ":(exclude).dockerignore"
                if ($Status) {
                    Write-Host "Local changes found in $($Service.Name); skipping git update."
                } else {
                    git fetch origin $Service.Branch
                    git checkout $Service.Branch
                    git pull --ff-only origin $Service.Branch
                }
            } finally {
                Pop-Location
            }
        }

        Copy-Item -Force (Join-Path $DockerfilesDir $Service.Dockerfile) (Join-Path $Target "Dockerfile")
        Copy-Item -Force (Join-Path $DockerfilesDir ".dockerignore") (Join-Path $Target ".dockerignore")
    } catch {
        $Failures += "$($Service.Name): $($_.Exception.Message)"
    }
}

$EnvFile = Join-Path $Root ".env"
$EnvExample = Join-Path $Root ".env.example"
if (-not (Test-Path $EnvFile)) {
    Copy-Item $EnvExample $EnvFile
    Write-Host "Created .env from .env.example. Review it before starting services."
}

if ($Failures.Count -gt 0) {
    Write-Host "Bootstrap completed with failures:"
    $Failures | ForEach-Object { Write-Host " - $_" }
    exit 1
}

if (-not $SkipBuild) {
    Push-Location $Root
    try {
        docker compose --profile full build
    } finally {
        Pop-Location
    }
}

Write-Host "Bootstrap complete."
