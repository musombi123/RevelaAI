param(
    [string]$Model = "gemma4:e2b"
)
$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
$Ollama = Get-Command ollama -ErrorAction SilentlyContinue
if (-not $Ollama) {
    throw "Ollama is not installed. Install it from https://ollama.com/download first."
}
$env:OLLAMA_MODELS = Join-Path $Root "models"
$env:OLLAMA_HOST = "127.0.0.1:11434"
New-Item -ItemType Directory -Force -Path $env:OLLAMA_MODELS | Out-Null
Write-Host "This downloads the selected model into the USB model folder. Internet is required for preparation." -ForegroundColor Yellow
Write-Host "Ensure no other Ollama server is running with a different OLLAMA_MODELS path." -ForegroundColor Yellow
Write-Host "Start the USB-local Ollama server in another PowerShell window using .\Start-LocalAI.ps1."
Read-Host "After the USB-local Ollama server is ready, press Enter to pull $Model"
& ollama pull $Model
if ($LASTEXITCODE -ne 0) { throw "Model download failed." }
Write-Host "Model downloaded. Test offline after disconnecting the internet." -ForegroundColor Green
