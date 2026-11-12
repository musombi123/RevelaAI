param(
  [string]$Root = "",
  [string]$Output = "",
  [switch]$NpmAudit,
  [switch]$ListDrives
)

$ErrorActionPreference = "Stop"
$Here = Split-Path -Parent $MyInvocation.MyCommand.Path
$EmbeddedPython = Join-Path $Here "runtimes\python-win-x64\python.exe"
$env:PYTHONPATH = Join-Path $Here "src"

if (Test-Path -LiteralPath $EmbeddedPython) {
  $Python = $EmbeddedPython
} else {
  $PythonCommand = Get-Command python -ErrorAction SilentlyContinue
  if (!$PythonCommand) { $PythonCommand = Get-Command py -ErrorAction SilentlyContinue }
  if (!$PythonCommand) {
    throw "Python 3.10+ is required for Workspace Audit. Use the embedded runtime in the released USB ZIP."
  }
  $Python = $PythonCommand.Source
}

if ($ListDrives) {
  & $Python -m revela_fieldkit drives
  exit $LASTEXITCODE
}

if ([string]::IsNullOrWhiteSpace($Root)) {
  Write-Host ""
  Write-Host "REVELAAI WORKSPACE AUDITOR" -ForegroundColor Cyan
  Write-Host "1. List mounted drives"
  Write-Host "2. Audit a repository or mounted volume"
  $choice = Read-Host "Choose an action"
  if ($choice -eq "1") {
    & $Python -m revela_fieldkit drives
    exit $LASTEXITCODE
  }
  if ($choice -ne "2") { exit 0 }
  $Root = Read-Host "Enter the exact repository or drive path you are authorized to inspect"
}

if (!(Test-Path -LiteralPath $Root -PathType Container)) {
  throw "Audit root is not an existing directory: $Root"
}

$Arguments = @("-m", "revela_fieldkit", "audit", "--root", $Root, "--authorized")
if (![string]::IsNullOrWhiteSpace($Output)) { $Arguments += @("--out", $Output) }
if ($NpmAudit) {
  Write-Host "Network access is enabled only for npm audit advisory lookup." -ForegroundColor Yellow
  $Arguments += "--npm-audit"
}
Write-Host "Running read-only local diagnostics for: $Root" -ForegroundColor Cyan
& $Python @Arguments
exit $LASTEXITCODE
