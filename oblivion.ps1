# Windows launcher: finds a Python 3.11+ and runs the CLI.  Usage: .\oblivion.ps1 deploy --host windows-audio
$here = Split-Path -Parent $MyInvocation.MyCommand.Path
$candidates = @(@("py", "-3"), @("python"), @("python3"))
foreach ($c in $candidates) {
    if (Get-Command $c[0] -ErrorAction SilentlyContinue) {
        $extra = @($c | Select-Object -Skip 1)
        & $c[0] @extra -c "import sys; sys.exit(sys.version_info < (3, 11))" 2>$null
        if ($LASTEXITCODE -eq 0) {
            & $c[0] @extra "$here\oblivion.py" @args
            exit $LASTEXITCODE
        }
    }
}
Write-Error "oblivion needs Python 3.11+ (install from python.org and tick 'Add to PATH')"
exit 2
