$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location -LiteralPath $Root
$Runtime = Join-Path $Root "runtimes\python-win-x64\python.exe"
$env:PYTHONPATH = Join-Path $Root "src"

if (Test-Path $Runtime) {
    & $Runtime -m revela_fieldkit menu
    exit $LASTEXITCODE
}

$PythonLauncher = Get-Command py -ErrorAction SilentlyContinue
if ($PythonLauncher) {
    & py -3 -c "import sys; raise SystemExit(0 if sys.version_info >= (3, 10) else 1)"
    if ($LASTEXITCODE -eq 0) {
        & py -3 -m revela_fieldkit menu
        exit $LASTEXITCODE
    }
}

$Python = Get-Command python -ErrorAction SilentlyContinue
if ($Python) {
    & python -c "import sys; raise SystemExit(0 if sys.version_info >= (3, 10) else 1)"
    if ($LASTEXITCODE -eq 0) {
        & python -m revela_fieldkit menu
        exit $LASTEXITCODE
    }
}

Write-Host "No compatible Python runtime found." -ForegroundColor Red
Write-Host "Run .\prepare-windows-runtime.ps1 to place an isolated Python runtime on this USB."
exit 1
