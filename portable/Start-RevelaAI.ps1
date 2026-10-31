$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
$Runtime = Join-Path $Root "runtimes\python-win-x64\python.exe"
$env:PYTHONPATH = Join-Path $Root "src"

if (Test-Path $Runtime) {
    & $Runtime -m revela_fieldkit menu
    exit $LASTEXITCODE
}

$Python = Get-Command py -ErrorAction SilentlyContinue
if ($Python) {
    & py -3 -m revela_fieldkit menu
    if ($LASTEXITCODE -eq 0) { exit 0 }
}

$Python = Get-Command python -ErrorAction SilentlyContinue
if ($Python) {
    & python -m revela_fieldkit menu
    exit $LASTEXITCODE
}

Write-Host "No compatible Python runtime found." -ForegroundColor Red
Write-Host "Run .\prepare-windows-runtime.ps1 to place an isolated Python runtime on this USB."
exit 1
