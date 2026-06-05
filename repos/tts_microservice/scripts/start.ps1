param(
    [Parameter(ValueFromRemainingArguments = $true)]
    [string[]]$ForwardedArgs
)

$ErrorActionPreference = "Stop"
$Launcher = Resolve-Path (Join-Path $PSScriptRoot "..\..\..\FULL_OBLIVION\scripts\start.ps1")
& $Launcher @ForwardedArgs
exit $LASTEXITCODE
