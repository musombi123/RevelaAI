$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location -LiteralPath $Root

# Prefer the self-contained Go Field Engine. It does not need Ollama or Go installed.
$Native = Join-Path $Root "bin\windows-amd64\revela-field.exe"
if (Test-Path $Native) {
    & $Native menu
    exit $LASTEXITCODE
}

# Keep the Python evidence/case-workspace tools as a compatibility fallback.
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

Write-Host "No compatible native Field Engine or Python runtime found." -ForegroundColor Red
Write-Host "Use the CI-built USB Edition or run .\prepare-windows-runtime.ps1 for the Python companion."
exit 1
