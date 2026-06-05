param(
    [ValidateSet("full", "brain-remote", "windows-audio", "windows-speaker", "software-only", "audio-only", "raspberry-services")]
    [string]$Scenario = "full"
)

$ErrorActionPreference = "Stop"
$Root = Resolve-Path (Join-Path $PSScriptRoot "..")

$ProfilesByScenario = @{
    "full" = @("full")
    "brain-remote" = @("brain")
    "windows-audio" = @("brain", "stt", "tts")
    "windows-speaker" = @("brain", "microphone", "stt", "tts")
    "software-only" = @("stt", "tts")
    "audio-only" = @("audio")
    "raspberry-services" = @("stt", "tts", "speaker")
}

$Profiles = $ProfilesByScenario[$Scenario]
$EnvOverridesByScenario = @{
    "windows-audio" = @{
        "BRAIN_MICROPHONE_BASE_URL" = "http://host.docker.internal:8000"
        "BRAIN_SPEAKER_BASE_URL" = "http://host.docker.internal:8003"
        "BRAIN_STARTUP_PREFLIGHT_ENABLED" = "false"
    }
    "windows-speaker" = @{
        "BRAIN_SPEAKER_BASE_URL" = "http://host.docker.internal:8003"
        "BRAIN_STARTUP_PREFLIGHT_ENABLED" = "false"
    }
}
$ComposeArgs = @()
foreach ($Profile in $Profiles) {
    $ComposeArgs += @("--profile", $Profile)
}

Write-Host "FULL_OBLIVION start from scratch"
Write-Host "Scenario: $Scenario"
Write-Host "Profiles: $($Profiles -join ', ')"

if ($EnvOverridesByScenario.ContainsKey($Scenario)) {
    foreach ($Name in $EnvOverridesByScenario[$Scenario].Keys) {
        $Value = $EnvOverridesByScenario[$Scenario][$Name]
        [Environment]::SetEnvironmentVariable($Name, $Value, "Process")
        Write-Host "$Name=$Value"
    }
}

Push-Location $Root
try {
    Write-Host ""
    Write-Host "Step 1/2: bootstrap repositories and generated Dockerfiles..."
    & .\scripts\repo\bootstrap.ps1 -SkipBuild

    Write-Host ""
    Write-Host "Step 2/2: build and start containers..."
    docker compose @ComposeArgs up -d --build
    docker compose @ComposeArgs ps

    Write-Host ""
    Write-Host "Started scenario: $Scenario"
} finally {
    Pop-Location
}
