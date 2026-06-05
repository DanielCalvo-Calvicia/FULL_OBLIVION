$RequiredRepos = @(
    "brain_microservice",
    "microphone_microservice",
    "stt_microservice",
    "tts_microservice",
    "speaker_microservice"
)

function Ensure-Repos {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Root
    )

    $Missing = @()
    foreach ($Repo in $RequiredRepos) {
        if (-not (Test-Path (Join-Path $Root "repos\$Repo"))) {
            $Missing += $Repo
        }
    }

    if ($Missing.Count -gt 0) {
        Write-Host "Missing cloned service repositories:"
        foreach ($Repo in $Missing) {
            Write-Host " - repos/$Repo"
        }
        Write-Host ""
        Write-Host "Run bootstrap first:"
        Write-Host "  .\scripts\repo\bootstrap.ps1"
        Write-Host ""
        Write-Host "Or, on Linux:"
        Write-Host "  ./scripts/repo/bootstrap.sh"
        exit 1
    }
}
